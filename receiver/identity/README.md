# Accessory identity (not in git)

CarPlay requires an MFi-authenticated accessory. The receiver reads two files that are deliberately
**not** included in this repository, its packages or its tests:

```
identity/offline-mfi/identity.pk8       # PKCS#8 EC P-256 private key
identity/offline-mfi/certificate.p7b    # accessory certificate (Apple Accessories CA)
```

`identity/` is ignored by Git. On the box they live in `/opt/autoplay/identity/offline-mfi/`
(`run-receiver.py` passes `--identity-dir /opt/autoplay/identity`); on a desk, point
`--identity-dir` at a directory containing `offline-mfi/`. Nothing downloads them: the box's
status model reports `identity: missing` until the files are there, and `provided` afterwards.

How to obtain a legitimate pair is outside this project's scope. AutoPlay is not an
Apple-certified product; a shared identity circulating publicly may be revoked by Apple at any
time, and this project does not redistribute one (`../../docs/SECURITY.md`, `../../NOTICE.md`).

Verify that a pair signs correctly with:

```sh
./gradlew :server:test --tests '*MfiIdentityTest*'
```
