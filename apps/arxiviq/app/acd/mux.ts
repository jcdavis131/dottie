/**
 * Invariant 05: One channel, many streams — PTY bytes, file transfer chunks,
 * and ISL HTTP all multiplex over a single WebSocket. One Yubikey touch covers every operation.
 * Zero-deps mux shim.
 */

export type StreamType = 'pty' | 'file' | 'isl' | 'rpc';

export type MuxFrame = {
  sid: number; // stream id
  type: StreamType;
  payload: Uint8Array;
  seq: number;
};

export class MuxChannel {
  private nextSid = 1;
  private seqMap = new Map<number, number>();
  private backpressure = 0;
  public authTag: string | null = null;
  private ws: { send: (b:Uint8Array)=>void } | null = null;

  constructor(ws?: { send:(b:Uint8Array)=>void }) {
    if (ws) this.ws = ws;
  }

  // One Yubi touch — covers all streams on this WebSocket
  authenticateOnce(tag:string) {
    this.authTag = tag;
    return { ok:true, tag, covers:'pty+file+isl+rpc' as const };
  }

  openStream(type:StreamType): number {
    if (!this.authTag) throw new Error('Must authenticate once before opening streams — one Yubi touch per invariant 05');
    const sid = this.nextSid++;
    this.seqMap.set(sid, 0);
    return sid;
  }

  encode(frame: MuxFrame): Uint8Array {
    // Simple framing: [sid(4) | type(1) | seq(4) | len(4) | payload]
    const enc = new TextEncoder();
    const typeCode = { pty:0, file:1, isl:2, rpc:3 }[frame.type];
    const header = new Uint8Array(13);
    new DataView(header.buffer).setUint32(0, frame.sid);
    header[4] = typeCode;
    new DataView(header.buffer).setUint32(5, frame.seq);
    new DataView(header.buffer).setUint32(9, frame.payload.length);
    const out = new Uint8Array(header.length + frame.payload.length);
    out.set(header,0);
    out.set(frame.payload, header.length);
    this.backpressure += out.length;
    if (this.backpressure > 1<<20) {
      // simple backpressure — pause producers
      // caller should check shouldPause flag
    }
    return out;
  }

  decode(buf:Uint8Array): MuxFrame {
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const sid = dv.getUint32(0);
    const typeCode = buf[4] as 0|1|2|3;
    const seq = dv.getUint32(5);
    const len = dv.getUint32(9);
    const payload = buf.slice(13, 13+len);
    const type = (['pty','file','isl','rpc'] as const)[typeCode];
    return { sid, type, payload, seq };
  }

  send(type:StreamType, payload:Uint8Array) {
    const sid = type==='rpc' ? 0 : this.openStream(type); // rpc over sid 0 control
    const seq = this.seqMap.get(sid) ?? 0;
    const frame = { sid, type, payload, seq };
    const enc = this.encode(frame);
    this.seqMap.set(sid, seq+1);
    this.ws?.send(enc);
    this.backpressure = Math.max(0, this.backpressure - 128); // drain heuristic
    return sid;
  }

  shouldPause() { return this.backpressure > (512*1024); }

  // Demux loop consumer calls onMessage
  onMessage(raw:Uint8Array, handler:(f:MuxFrame)=>void) {
    const f = this.decode(raw);
    handler(f);
  }

  snapshot() {
    return { streams: this.seqMap.size, backpressure: this.backpressure, authed: !!this.authTag };
  }
}

// One channel instance per host — enforces 1 tunnel invariant
export const perHostMux = new Map<string, MuxChannel>();
export function getMuxForHost(host:string): MuxChannel {
  if (!perHostMux.has(host)) perHostMux.set(host, new MuxChannel());
  return perHostMux.get(host)!;
}
