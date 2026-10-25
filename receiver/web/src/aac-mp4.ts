/** Minimal ISO-BMFF framing for the receiver's raw AAC-LC access units (1024 samples). */
const join = (...parts: Uint8Array[]) => { const b=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));let i=0;for(const p of parts){b.set(p,i);i+=p.length;}return b; };
const text = (s:string) => new TextEncoder().encode(s);
const u32 = (...values:number[]) => { const b=new Uint8Array(values.length*4);const v=new DataView(b.buffer);values.forEach((x,i)=>v.setUint32(i*4,x));return b; };
const u16 = (...values:number[]) => { const b=new Uint8Array(values.length*2);const v=new DataView(b.buffer);values.forEach((x,i)=>v.setUint16(i*2,x));return b; };
const zeros = (n:number) => new Uint8Array(n);
const box = (type:string,...parts:Uint8Array[]) => { const data=join(...parts);return join(u32(data.length+8),text(type),data); };
const full = (type:string,flags:number,...parts:Uint8Array[]) => box(type,u32(flags),...parts);
const matrix = u32(0x10000,0,0,0,0x10000,0,0,0,0x40000000);
function descriptor(tag:number,data:Uint8Array):Uint8Array {
  const length=[data.length&127];let n=data.length>>>7;while(n){length.unshift((n&127)|128);n>>>=7;}
  return join(new Uint8Array([tag,...length]),data);
}
export function aacInit(rate:number,channels:number,asc:Uint8Array):Uint8Array {
  if(rate<=0||rate>65535||channels<1||channels>2||asc.length<2) throw new Error('Unsupported AAC configuration');
  const es=descriptor(3,join(u16(1),new Uint8Array([0]),descriptor(4,join(new Uint8Array([0x40,0x15,0,0,0]),u32(256000,128000),descriptor(5,asc))),descriptor(6,new Uint8Array([2]))));
  const mp4a=box('mp4a',zeros(6),u16(1),zeros(8),u16(channels,16,0,0),u32(rate*65536),full('esds',0,es));
  const stbl=box('stbl',full('stsd',0,u32(1),mp4a),full('stts',0,u32(0)),full('stsc',0,u32(0)),full('stsz',0,u32(0,0)),full('stco',0,u32(0)));
  const dinf=box('dinf',full('dref',0,u32(1),full('url ',1)));
  const mdia=box('mdia',full('mdhd',0,u32(0,0,rate,0),u16(0x55c4,0)),full('hdlr',0,u32(0),text('soun'),zeros(12),text('F50 Audio\0')),box('minf',full('smhd',0,u16(0,0)),dinf,stbl));
  const trak=box('trak',full('tkhd',7,u32(0,0,1,0,0),zeros(8),u16(0,0,0x100,0),matrix,u32(0,0)),mdia);
  const mvhd=full('mvhd',0,u32(0,0,rate,0,0x10000),u16(0x100,0),zeros(8),matrix,zeros(24),u32(2));
  return join(box('ftyp',text('isom'),u32(0x200),text('isomiso6mp41')),box('moov',mvhd,trak,box('mvex',full('trex',0,u32(1,1,1024,0,0)))));
}
export function aacFragment(sequence:number,sampleTime:number,frames:Uint8Array[]):Uint8Array {
  const make=(offset:number)=>box('moof',full('mfhd',0,u32(sequence)),box('traf',full('tfhd',0x020000,u32(1)),full('tfdt',0x01000000,u32(Math.floor(sampleTime/4294967296),sampleTime>>>0)),full('trun',0x301,u32(frames.length,offset),...frames.map(f=>u32(1024,f.length)))));
  const preliminary=make(0),moof=make(preliminary.length+8);
  return join(moof,box('mdat',...frames));
}
