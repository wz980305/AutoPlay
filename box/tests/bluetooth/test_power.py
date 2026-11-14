"""platform_openwrt.power_adapter against a real private D-Bus and a mock BlueZ, NOT radio/iPhone tests.

Since 1.6.3 the box powers and names the adapter over D-Bus instead of bluetoothctl, which crashed after
mu300-linux 25.12.6 (2026-11-14: "Error relocating: g_list_delete_link: symbol not found"). Needs dbus-daemon
and dbus-next 0.2.3, like test_bluez."""
import asyncio
import os
from pathlib import Path
import sys
import unittest
import unittest.mock

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/onecloud'))
import platform_openwrt as ow

ADAPTER = '/org/bluez/hci0'
OTHER = '/org/bluez/hci1'
DEVICE = ADAPTER + '/dev_12_34_56_78_9A_BC'


class PowerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.daemon = await asyncio.create_subprocess_exec(
            os.environ.get('DBUS_DAEMON_BINARY', 'dbus-daemon'),
            '--config-file=' + str(Path(__file__).with_name('session.conf')), '--nofork', '--print-address=1',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.address = (await self.daemon.stdout.readline()).decode().strip()
        self.bus = await MessageBus(bus_address=self.address).connect()
        await self.bus.request_name('org.bluez')
        self.adapters = {ADAPTER: {'Powered': False, 'Alias': 'f50'}}
        self.devices = {}
        self.sets = []
        self.refuse = None
        self.bus.add_message_handler(self.handle)

    async def asyncTearDown(self):
        if self.bus.connected:
            self.bus.disconnect()
            await asyncio.wait_for(self.bus.wait_for_disconnect(), 2)
        self.bus._stream.close()   # dbus-next 0.2.3 leaves its socket open (bridge.ManagedBus)
        self.bus._sock.close()
        self.daemon.terminate()
        await self.daemon.wait()

    def objects(self):
        out = {path: {'org.bluez.Adapter1': {'Powered': Variant('b', props['Powered']),
                                             'Alias': Variant('s', props['Alias'])}}
               for path, props in self.adapters.items()}
        for path, (adapter, connected) in self.devices.items():
            out[path] = {'org.bluez.Device1': {'Adapter': Variant('o', adapter), 'Connected': Variant('b', connected)}}
        return out

    def handle(self, message):
        if message.message_type != MessageType.METHOD_CALL:
            return None
        if message.member == 'GetManagedObjects':
            return Message.new_method_return(message, 'a{oa{sa{sv}}}', [self.objects()])
        if message.interface == 'org.freedesktop.DBus.Properties' and message.path in self.adapters:
            interface, key = message.body[0], message.body[1]
            if interface != 'org.bluez.Adapter1':
                return Message.new_error(message, 'org.freedesktop.DBus.Error.InvalidArgs', interface)
            if message.member == 'Get':
                value = self.adapters[message.path][key]
                return Message.new_method_return(message, 'v', [Variant('b' if key == 'Powered' else 's', value)])
            if message.member == 'Set':
                value = message.body[2].value
                self.sets.append((message.path, key, value))
                if self.refuse == key:
                    return Message.new_error(message, 'org.bluez.Error.Failed', 'test refusal')
                self.adapters[message.path][key] = value
                if key == 'Powered' and not value:   # BlueZ drops the adapter's links when it powers off
                    self.devices = {path: (adapter, connected and adapter != message.path)
                                    for path, (adapter, connected) in self.devices.items()}
                return Message.new_method_return(message)
        return Message.new_error(message, 'org.freedesktop.DBus.Error.UnknownMethod', message.member)

    async def power(self, name='AutoPlay'):
        return await asyncio.wait_for(ow.power_adapter(name, bus_address=self.address), 10)

    async def test_powers_on_and_names_the_adapter(self):
        self.assertTrue(await self.power())
        self.assertEqual(self.sets, [(ADAPTER, 'Powered', True), (ADAPTER, 'Alias', 'AutoPlay')])
        self.assertEqual(self.adapters[ADAPTER], {'Powered': True, 'Alias': 'AutoPlay'})

    async def test_a_leftover_phone_link_power_cycles_the_adapter_once(self):
        self.devices = {DEVICE: (ADAPTER, True)}
        self.assertTrue(await self.power())
        self.assertEqual(self.sets, [(ADAPTER, 'Powered', True), (ADAPTER, 'Powered', False),
                                     (ADAPTER, 'Powered', True), (ADAPTER, 'Alias', 'AutoPlay')])
        self.assertFalse(self.devices[DEVICE][1])

    async def test_a_link_on_another_adapter_or_a_paired_phone_is_left_alone(self):
        self.adapters[OTHER] = {'Powered': True, 'Alias': 'other'}
        self.devices = {DEVICE: (ADAPTER, False), OTHER + '/dev_02_00_00_00_00_02': (OTHER, True)}
        self.assertTrue(await self.power())
        self.assertEqual(self.sets, [(ADAPTER, 'Powered', True), (ADAPTER, 'Alias', 'AutoPlay')])

    async def test_refused_power_on_is_false(self):
        self.refuse = 'Powered'
        self.assertFalse(await self.power())
        self.assertEqual(self.sets, [(ADAPTER, 'Powered', True)])

    async def test_a_refused_alias_still_counts_as_powered(self):
        """system-alias was best effort before 1.6.3 too; bluez.conf's Name=AutoPlay stands in."""
        self.refuse = 'Alias'
        self.assertTrue(await self.power())
        self.assertTrue(self.adapters[ADAPTER]['Powered'])

    async def test_no_adapter_yet_is_false(self):
        self.adapters = {}
        self.assertFalse(await self.power())
        self.assertEqual(self.sets, [])

    async def test_no_bluez_on_the_bus_is_an_error_the_caller_turns_into_false(self):
        self.bus.disconnect()
        with self.assertRaises(RuntimeError):
            await self.power()

    async def test_power_bluetooth_end_to_end_over_the_private_bus(self):
        """The supervisor's entry point (sync, in its own thread, as BluetoothManager runs it) on the same bus."""
        with unittest.mock.patch.dict(os.environ, {'DBUS_SYSTEM_BUS_ADDRESS': self.address}):
            self.assertTrue(await asyncio.to_thread(ow.OpenWrtPlatform().power_bluetooth))
        self.assertEqual(self.adapters[ADAPTER], {'Powered': True, 'Alias': ow.BLUETOOTH_NAME})
