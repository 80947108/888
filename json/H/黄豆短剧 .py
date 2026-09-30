/**
 * 黄豆短剧 ForwardWidget v3.1.1
 * 平台：lzlukvca.cc (黄豆短剧)
 *
 * === v3.1.0 新增分类 + 动态分类代码解析 ===
 * 新增综艺/黑料/国产传媒三个分类栏目
 * 分类代码不再硬编码，从 /drama/navList API 动态获取真实 code
 * → 即使枚举值与 API code 不一致，也能通过名称模糊匹配自动修正
 *
 *
 * === v2.1.0 Cloudflare Worker 代理 ===
 * 解决真机 Forward App 无法发送二进制 body 的问题：
 *
 * 核心问题（widget-adaptor.ts 源码确认）：
 *   fetchOptions.body = typeof body === 'string' ? body : JSON.stringify(body);
 *   → 非 string body（ArrayBuffer）被 JSON.stringify → "{}"
 *   → string body 中的字节 >= 0x80 被 UTF-8 多字节编码 → 二进制损坏
 *   → 结论：Widget.http.post 无法直接发送二进制数据
 *
 * 解决方案：Cloudflare Worker 中继
 *   1. 模块将加密二进制 body 编码为 base64 字符串（纯 ASCII）
 *   2. 通过 Widget.http.post 发送 JSON { url, body_b64, headers } 到 Worker
 *      → JSON 字符串全是 ASCII，不受 UTF-8 编码影响
 *   3. Worker 解码 base64 → 原始二进制，转发到黄豆短剧 API 服务器
 *   4. Worker 收到二进制响应 → 编码为 base64 → JSON 返回给模块
 *   5. 模块解码 base64 → 解密 → 正常处理
 *
 * 传输优先级：
 *   1. fetch()        — 直连（在线测试工具 / Node.js 环境可用）
 *   2. XMLHttpRequest  — 直连（浏览器环境可用）
 *   3. Worker 代理     — 通过 CF Worker 中继（真机 + proxyUrl 配置时使用）
 *   4. Widget.http.post — 直连（诊断用，已知无法发送二进制）
 *
 * 使用方法：
 *   - 在线测试：直接加载，fetch 可用，无需额外配置
 *   - 真机使用：部署 huangdou-cf-worker-proxy.js 到 Cloudflare Worker
 *     → 在模块设置「代理地址」填入 Worker URL（如 https://xxx.workers.dev）
 *
 * === 其他功能（继承自 v2.0.0）===
 * - 8 条线路容错，主线路失败自动切换
 * - 分类浏览：黄豆原创/AI漫剧/二次元/擦边/真人/综艺/黑料/国产传媒
 * - 分类代码动态解析（navList API → 真实 code）
 * - 搜索 + 剧集详情
 * - VIP 剧集直接播放（?line=free 无鉴权）
 * - AES-256-CBC 加密通信
 *
 * 参考：
 *   - Scripting App 黄豆短剧 by OkadaMei (client.ts / proxy.ts)
 *   - Forward App fg999 模块（Widget API 参考）
 */

// ==================== Metadata ====================

WidgetMetadata = {
  id: "forward.huangdou",
  title: "黄豆短剧",
  version: "3.1.1",
  requiredVersion: "0.0.1",
  description: "黄豆短剧 — 分类浏览+搜索+HLS播放\nVIP剧集直接解锁，无需登录会员\n支持黄豆原创/AI漫剧/二次元/擦边/真人/综艺/黑料/国产传媒等分类\n分类代码自动从API获取，无需手动维护\n多线路容错，播放更稳定\n真机需配置代理地址（部署CF Worker）",
  author: "Forward",
  site: "https://lzlukvca.cc",
  icon: "https://lzlukvca.cc/favicon.ico",
  detailCacheDuration: 0,
  globalParams: [
    {
      name: "proxyUrl",
      title: "代理地址",
      type: "input",
      value: "",
      description: "Cloudflare Worker 代理 URL（真机必填）\n部署 huangdou-cf-worker-proxy.js 到 CF Worker\n填入 Worker URL，如 https://xxx.workers.dev\n在线测试工具无需填写（自动用 fetch 直连）"
    }
  ],
  modules: [
    {
      id: "loadList",
      title: "短剧列表",
      functionName: "loadList",
      cacheDuration: 60,
      params: [
        {
          name: "category",
          title: "分类",
          type: "enumeration",
          value: "yuandou",
          enumOptions: [
            { title: "黄豆原创", value: "yuandou" },
            { title: "AI漫剧", value: "aiman" },
            { title: "二次元", value: "erciyuan" },
            { title: "擦边短剧", value: "caibian" },
            { title: "真人短剧", value: "zhenren" },
            { title: "综艺", value: "zongyi" },
            { title: "黑料", value: "heiliao" },
            { title: "国产传媒", value: "guochuanmei" }
          ]
        },
        { name: "page", title: "页码", type: "page" },
        { name: "count", title: "数量", type: "count", value: "30" }
      ]
    },
    {
      id: "loadResource",
      title: "播放",
      functionName: "loadResource",
      type: "stream",
      params: []
    }
  ],
  search: {
    title: "搜索短剧",
    functionName: "search",
    params: [
      { name: "keyword", title: "关键词", type: "input" },
      { name: "page", title: "页码", type: "page" }
    ]
  }
};

// ==================== Constants ====================

var MASTER_KEY = "7961beb44246e3012ce228d6b5ced05a";
var UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1";

// 多线路（从 proxy.ts 移植）
var LINES = [
  { code: "china_1", base: "https://lzlukvca.cc" },
  { code: "china_1", base: "https://psfxhhox.top" },
  { code: "china_2", base: "https://sxqirtho.top" },
  { code: "china_3", base: "https://qicuknlj.top" },
  { code: "china_4", base: "https://hddj05.com" },
  { code: "china_5", base: "https://hddj06.com" },
  { code: "china_6", base: "https://hddj07.com" },
  { code: "oversea_1", base: "https://hvthtcpa.top" }
];

var _loginState = null;
var _deviceId = null;
var _preferredLine = LINES[0].base; // 记住成功线路
var _proxyUrl = ""; // Cloudflare Worker 代理 URL（真机用）

// 从 params 提取全局配置（每个模块函数入口调用）
function initConfig(params) {
  if (params && params.proxyUrl) {
    var url = String(params.proxyUrl).trim();
    if (url && url !== _proxyUrl) _proxyUrl = url;
  }
}

// ==================== SHA-256 ====================

var K256 = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];

function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }

function sha256Bytes(data) {
  var bytes = data instanceof Uint8Array ? Array.prototype.slice.call(data) : data.slice();
  var bitLen = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  var hi = Math.floor(bitLen / 0x100000000), lo = bitLen >>> 0;
  bytes.push((hi>>>24)&0xff,(hi>>>16)&0xff,(hi>>>8)&0xff,hi&0xff,(lo>>>24)&0xff,(lo>>>16)&0xff,(lo>>>8)&0xff,lo&0xff);
  var h0=0x6a09e667,h1=0xbb67ae85,h2=0x3c6ef372,h3=0xa54ff53a,h4=0x510e527f,h5=0x9b05688c,h6=0x1f83d9ab,h7=0x5be0cd19;
  var w = new Array(64);
  for (var i=0; i<bytes.length; i+=64) {
    for (var t=0; t<16; t++) { var o=i+t*4; w[t]=((bytes[o]<<24)|(bytes[o+1]<<16)|(bytes[o+2]<<8)|bytes[o+3])>>>0; }
    for (var t=16; t<64; t++) { var s0=rotr(w[t-15],7)^rotr(w[t-15],18)^(w[t-15]>>>3); var s1=rotr(w[t-2],17)^rotr(w[t-2],19)^(w[t-2]>>>10); w[t]=(w[t-16]+s0+w[t-7]+s1)>>>0; }
    var a=h0,b=h1,c=h2,d=h3,e=h4,f=h5,g=h6,h=h7;
    for (var t=0; t<64; t++) { var S1=rotr(e,6)^rotr(e,11)^rotr(e,25); var ch=(e&f)^(~e&g); var t1=(h+S1+ch+K256[t]+w[t])>>>0; var S0=rotr(a,2)^rotr(a,13)^rotr(a,22); var maj=(a&b)^(a&c)^(b&c); var t2=(S0+maj)>>>0; h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0; }
    h0=(h0+a)>>>0;h1=(h1+b)>>>0;h2=(h2+c)>>>0;h3=(h3+d)>>>0;h4=(h4+e)>>>0;h5=(h5+f)>>>0;h6=(h6+g)>>>0;h7=(h7+h)>>>0;
  }
  var out=[]; var hs=[h0,h1,h2,h3,h4,h5,h6,h7];
  for (var j=0; j<8; j++) out.push((hs[j]>>>24)&0xff,(hs[j]>>>16)&0xff,(hs[j]>>>8)&0xff,hs[j]&0xff);
  return out;
}

function hmacSha256(keyBytes, msgBytes) {
  var k = keyBytes.slice();
  if (k.length > 64) k = sha256Bytes(k);
  while (k.length < 64) k.push(0);
  var ipad=[], opad=[];
  for (var i=0; i<64; i++) { ipad.push(k[i]^0x36); opad.push(k[i]^0x5c); }
  return sha256Bytes(opad.concat(sha256Bytes(ipad.concat(msgBytes))));
}

// ==================== AES-256 ====================

var SBOX=[0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16];

var INV_SBOX=[0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d];

function aesExpandKey(keyBytes) {
  var Nk = keyBytes.length / 4, Nr = Nk + 6;
  var w = [];
  for (var i=0; i<Nk; i++) w[i] = [keyBytes[i*4],keyBytes[i*4+1],keyBytes[i*4+2],keyBytes[i*4+3]];
  var rcon = 1;
  for (var i=Nk; i<4*(Nr+1); i++) {
    var temp = w[i-1].slice();
    if (i % Nk === 0) { temp=[temp[1],temp[2],temp[3],temp[0]]; temp=[SBOX[temp[0]],SBOX[temp[1]],SBOX[temp[2]],SBOX[temp[3]]]; temp[0]^=rcon; rcon=(rcon<<1)^(rcon&0x80?0x11b:0); }
    else if (Nk>6 && i%Nk===4) { temp=[SBOX[temp[0]],SBOX[temp[1]],SBOX[temp[2]],SBOX[temp[3]]]; }
    var prev = w[i-Nk]; w[i]=[prev[0]^temp[0],prev[1]^temp[1],prev[2]^temp[2],prev[3]^temp[3]];
  }
  var rk = new Array((Nr+1)*16);
  for (var r=0; r<Nr+1; r++) for (var c=0; c<4; c++) { var wv=w[r*4+c]; rk[r*16+c*4]=wv[0]; rk[r*16+c*4+1]=wv[1]; rk[r*16+c*4+2]=wv[2]; rk[r*16+c*4+3]=wv[3]; }
  return { rk: rk, Nr: Nr };
}

function xtime(a) { return ((a<<1)^(a&0x80?0x1b:0))&0xff; }

function aesBlockDecrypt(state, rk, Nr) {
  var s = state.slice();
  function addRoundKey(r) { for (var i=0; i<16; i++) s[i]^=rk[r*16+i]; }
  function invSubBytes() { for (var i=0; i<16; i++) s[i]=INV_SBOX[s[i]]; }
  function invShiftRows() { var t=s.slice(); s[0]=t[0];s[1]=t[13];s[2]=t[10];s[3]=t[7];s[4]=t[4];s[5]=t[1];s[6]=t[14];s[7]=t[11];s[8]=t[8];s[9]=t[5];s[10]=t[2];s[11]=t[15];s[12]=t[12];s[13]=t[9];s[14]=t[6];s[15]=t[3]; }
  function mul9(a){return xtime(xtime(xtime(a)))^a;} function mul11(a){return xtime(xtime(xtime(a)))^xtime(a)^a;} function mul13(a){return xtime(xtime(xtime(a)))^xtime(xtime(a))^a;} function mul14(a){return xtime(xtime(xtime(a)))^xtime(xtime(a))^xtime(a);}
  function invMixColumns() { for (var c=0; c<4; c++) { var i=c*4; var a0=s[i],a1=s[i+1],a2=s[i+2],a3=s[i+3]; s[i]=mul14(a0)^mul11(a1)^mul13(a2)^mul9(a3); s[i+1]=mul9(a0)^mul14(a1)^mul11(a2)^mul13(a3); s[i+2]=mul13(a0)^mul9(a1)^mul14(a2)^mul11(a3); s[i+3]=mul11(a0)^mul13(a1)^mul9(a2)^mul14(a3); } }
  addRoundKey(Nr);
  for (var r=Nr-1; r>0; r--) { invShiftRows(); invSubBytes(); addRoundKey(r); invMixColumns(); }
  invShiftRows(); invSubBytes(); addRoundKey(0);
  return s;
}

function aesBlockEncrypt(state, rk, Nr) {
  var s = state.slice();
  function addRoundKey(r) { for (var i=0; i<16; i++) s[i]^=rk[r*16+i]; }
  function subBytes() { for (var i=0; i<16; i++) s[i]=SBOX[s[i]]; }
  function shiftRows() { var t=s.slice(); s[0]=t[0];s[1]=t[5];s[2]=t[10];s[3]=t[15];s[4]=t[4];s[5]=t[9];s[6]=t[14];s[7]=t[3];s[8]=t[8];s[9]=t[13];s[10]=t[2];s[11]=t[7];s[12]=t[12];s[13]=t[1];s[14]=t[6];s[15]=t[11]; }
  function mixColumns() { for (var c=0; c<4; c++) { var i=c*4; var a0=s[i],a1=s[i+1],a2=s[i+2],a3=s[i+3]; s[i]=xtime(a0)^xtime(a1)^a1^a2^a3; s[i+1]=a0^xtime(a1)^xtime(a2)^a2^a3; s[i+2]=a0^a1^xtime(a2)^xtime(a3)^a3; s[i+3]=xtime(a0)^a0^a1^a2^xtime(a3); } }
  addRoundKey(0);
  for (var r=1; r<Nr; r++) { subBytes(); shiftRows(); mixColumns(); addRoundKey(r); }
  subBytes(); shiftRows(); addRoundKey(Nr);
  return s;
}

function aesCbcDecrypt(cipherBytes, keyBytes, ivBytes) {
  var rkObj = aesExpandKey(keyBytes); var rk = rkObj.rk, Nr = rkObj.Nr;
  var out = []; var prev = ivBytes.slice();
  for (var off=0; off<cipherBytes.length; off+=16) {
    var block = cipherBytes.slice(off, off+16);
    var dec = aesBlockDecrypt(block, rk, Nr);
    for (var i=0; i<16; i++) out.push(dec[i]^prev[i]);
    prev = block;
  }
  var padLen = out[out.length-1];
  if (padLen >= 1 && padLen <= 16) out.length -= padLen;
  return out;
}

function aesCbcEncrypt(plainBytes, keyBytes, ivBytes) {
  var rkObj = aesExpandKey(keyBytes); var rk = rkObj.rk, Nr = rkObj.Nr;
  var out = []; var prev = ivBytes.slice();
  for (var off=0; off<plainBytes.length; off+=16) {
    var block = plainBytes.slice(off, off+16);
    var xored = []; for (var i=0; i<16; i++) xored.push(block[i]^prev[i]);
    var enc = aesBlockEncrypt(xored, rk, Nr);
    for (var j=0; j<16; j++) out.push(enc[j]);
    prev = enc;
  }
  return out;
}

function pkcs7Pad(data) { var padLen = 16-(data.length%16); var out=data.slice(); for (var i=0; i<padLen; i++) out.push(padLen); return out; }

function randomBytes(n) { var out=[]; for (var i=0; i<n; i++) out.push(Math.floor(Math.random()*256)); return out; }

// ==================== Base64 / Hex / UTF8 ====================

var B64_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
var B64_REV = (function(){ var m={}; for (var i=0; i<64; i++) m[B64_CHARS[i]]=i; return m; })();

function base64ToBytes(str) {
  str = String(str).replace(/[^A-Za-z0-9+/=]/g, ''); var out=[]; var buffer=0, bits=0;
  for (var j=0; j<str.length; j++) { var ch=str[j]; if (ch==='=') break; buffer=(buffer<<6)|B64_REV[ch]; bits+=6; if (bits>=8) { bits-=8; out.push((buffer>>bits)&0xff); } }
  return out;
}

function bytesToBase64(bytes) {
  var out='';
  for (var i=0; i<bytes.length; i+=3) {
    var b0=bytes[i], b1=i+1<bytes.length?bytes[i+1]:0, b2=i+2<bytes.length?bytes[i+2]:0;
    var n=(b0<<16)|(b1<<8)|b2;
    out += B64_CHARS[(n>>>18)&63]+B64_CHARS[(n>>>12)&63]+B64_CHARS[(n>>>6)&63]+B64_CHARS[n&63];
  }
  var rem = bytes.length%3;
  if (rem===1) out=out.slice(0,-2)+'=='; else if (rem===2) out=out.slice(0,-1)+'=';
  return out;
}

function hexToBytes(hexStr) {
  var s = String(hexStr).replace(/[^0-9a-fA-F]/g, ''); var out=[];
  for (var i=0; i<s.length; i+=2) out.push(parseInt(s.substr(i,2),16));
  return out;
}

function bytesToHex(bytes) {
  var hex='0123456789abcdef'; var out='';
  for (var i=0; i<bytes.length; i++) out += hex[(bytes[i]>>4)&0xf] + hex[bytes[i]&0xf];
  return out;
}

function utf8ToBytes(str) {
  var out=[];
  for (var i=0; i<str.length; i++) {
    var c=str.charCodeAt(i);
    if (c>=0xd800 && c<=0xdbff && i+1<str.length) { var c2=str.charCodeAt(i+1); if (c2>=0xdc00 && c2<=0xdfff) { c=0x10000+((c-0xd800)<<10)+(c2-0xdc00); i++; } }
    if (c<0x80) out.push(c);
    else if (c<0x800) out.push(0xc0|(c>>6),0x80|(c&63));
    else if (c<0x10000) out.push(0xe0|(c>>12),0x80|((c>>6)&63),0x80|(c&63));
    else out.push(0xf0|(c>>18),0x80|((c>>12)&63),0x80|((c>>6)&63),0x80|(c&63));
  }
  return out;
}

function bytesToUtf8(bytes) {
  var out='';
  for (var i=0; i<bytes.length;) {
    var b=bytes[i];
    if (b<0x80) { out+=String.fromCharCode(b); i++; }
    else if (b<0xe0) { out+=String.fromCharCode(((b&0x1f)<<6)|(bytes[i+1]&0x3f)); i+=2; }
    else if (b<0xf0) { out+=String.fromCharCode(((b&0xf)<<12)|((bytes[i+1]&0x3f)<<6)|(bytes[i+2]&0x3f)); i+=3; }
    else { var cp=((b&0x7)<<18)|((bytes[i+1]&0x3f)<<12)|((bytes[i+2]&0x3f)<<6)|(bytes[i+3]&0x3f); var v=cp-0x10000; out+=String.fromCharCode(0xd800+(v>>10),0xdc00+(v&0x3ff)); i+=4; }
  }
  return out;
}

// ==================== Gzip Inflate (response decompression) ====================

function BitReader(bytes) { this.bytes=bytes; this.pos=0; this.bitPos=0; }
BitReader.prototype.readBits = function(n) { var val=0; for (var i=0; i<n; i++) { var byte=this.bytes[this.pos]; var bit=(byte>>this.bitPos)&1; val|=bit<<i; this.bitPos++; if (this.bitPos===8) { this.bitPos=0; this.pos++; } } return val; };
BitReader.prototype.alignByte = function() { if (this.bitPos>0) { this.bitPos=0; this.pos++; } };
BitReader.prototype.readByte = function() { this.alignByte(); return this.bytes[this.pos++]; };
BitReader.prototype.readUint16LE = function() { var a=this.readByte(), b=this.readByte(); return a|(b<<8); };

function buildHuffmanTable(lengths) {
  var maxLen=0; for (var i=0; i<lengths.length; i++) if (lengths[i]>maxLen) maxLen=lengths[i];
  var blCount=new Array(maxLen+1); for (var j=0; j<=maxLen; j++) blCount[j]=0;
  for (var j=0; j<lengths.length; j++) if (lengths[j]>0) blCount[lengths[j]]++;
  var nextCode=new Array(maxLen+1); var code=0;
  for (var bits=1; bits<=maxLen; bits++) { code=(code+blCount[bits-1])<<1; nextCode[bits]=code; }
  var codes=new Array(lengths.length);
  for (var sym=0; sym<lengths.length; sym++) { var l=lengths[sym]; if (l>0) { codes[sym]=nextCode[l]; nextCode[l]++; } else codes[sym]=-1; }
  return { lengths:lengths, codes:codes, maxLen:maxLen };
}

function huffmanDecode(reader, table) {
  var code=0, first=0, index=0;
  for (var len=1; len<=table.maxLen; len++) {
    code|=reader.readBits(1);
    var count=0; for (var j=0; j<table.lengths.length; j++) if (table.lengths[j]===len) count++;
    if (code-first<count) { var seen=0; for (var sym=0; sym<table.lengths.length; sym++) { if (table.lengths[sym]===len) { if (seen===code-first) return sym; seen++; } } }
    first+=count; first<<=1; code<<=1;
  }
  throw new Error('huffman decode fail');
}

var LENGTH_BASE=[3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258];
var LENGTH_EXTRA=[0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
var DIST_BASE=[1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577];
var DIST_EXTRA=[0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
var FIXED_LIT=new Array(288); for (var i=0; i<144; i++) FIXED_LIT[i]=8; for (var i=144; i<256; i++) FIXED_LIT[i]=9; for (var i=256; i<280; i++) FIXED_LIT[i]=7; for (var i=280; i<288; i++) FIXED_LIT[i]=8;
var FIXED_DIST=new Array(30); for (var i=0; i<30; i++) FIXED_DIST[i]=5;
var FIXED_LIT_TABLE=buildHuffmanTable(FIXED_LIT);
var FIXED_DIST_TABLE=buildHuffmanTable(FIXED_DIST);

function inflateHuffmanBlock(reader, out, tableLit, tableDist) {
  var guard=0;
  for (;;) { if (++guard>300000) throw new Error('inflate guard lit'); var sym=huffmanDecode(reader, tableLit); if (sym<256) { out.push(sym); continue; } if (sym===256) break; var li=sym-257; var length=LENGTH_BASE[li]+reader.readBits(LENGTH_EXTRA[li]); var dsym=huffmanDecode(reader, tableDist); var dist=DIST_BASE[dsym]+reader.readBits(DIST_EXTRA[dsym]); var start=out.length-dist; for (var i=0; i<length; i++) out.push(out[start+i]); }
}

function inflateDeflate(reader, out) {
  var guard=0;
  for (;;) {
    if (++guard>2000) throw new Error('inflate guard block');
    var bfinal=reader.readBits(1); var btype=reader.readBits(2);
    if (btype===0) { reader.alignByte(); var len=reader.readUint16LE(); reader.readUint16LE(); for (var i=0; i<len; i++) out.push(reader.readByte()); }
    else if (btype===1) { inflateHuffmanBlock(reader, out, FIXED_LIT_TABLE, FIXED_DIST_TABLE); }
    else if (btype===2) {
      var hlit=reader.readBits(5)+257; var hdist=reader.readBits(5)+1; var hclen=reader.readBits(4)+4;
      var order=[16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15];
      var clLengths=new Array(19); for (var j=0; j<19; j++) clLengths[j]=0;
      for (var j=0; j<hclen; j++) clLengths[order[j]]=reader.readBits(3);
      var clTable=buildHuffmanTable(clLengths);
      var lengths=[]; var dguard=0;
      while (lengths.length<hlit+hdist) {
        if (++dguard>30000) throw new Error('inflate guard dynamic');
        var s=huffmanDecode(reader, clTable);
        if (s<16) lengths.push(s);
        else if (s===16) { var prev=lengths[lengths.length-1]; var rep=reader.readBits(2)+3; for (var r=0; r<rep; r++) lengths.push(prev); }
        else if (s===17) { var rep=reader.readBits(3)+3; for (var r=0; r<rep; r++) lengths.push(0); }
        else { var rep=reader.readBits(7)+11; for (var r=0; r<rep; r++) lengths.push(0); }
      }
      var litTable=buildHuffmanTable(lengths.slice(0,hlit));
      var distTable=buildHuffmanTable(lengths.slice(hlit));
      inflateHuffmanBlock(reader, out, litTable, distTable);
    }
    if (bfinal) break;
  }
}

function gunzipBytes(data) {
  var out=[];
  if (data[0]===0x1f && data[1]===0x8b) {
    var p=10; var flags=data[3];
    if (flags&4) { var xlen=data[p]|(data[p+1]<<8); p+=2+xlen; }
    if (flags&8) { while (data[p]!==0) p++; p++; }
    if (flags&16) { while (data[p]!==0) p++; p++; }
    if (flags&2) p+=2;
    inflateDeflate(new BitReader(data.slice(p)), out);
  } else if ((data[0]&0x0f)===8) {
    inflateDeflate(new BitReader(data.slice(2, data.length-4)), out);
  } else {
    throw new Error('unknown compression');
  }
  return out;
}

// ==================== GZip Stored Block (for request compression) ====================

var CRC32_TABLE = (function() {
  var table = new Array(256);
  for (var i = 0; i < 256; i++) {
    var c = i;
    for (var j = 0; j < 8; j++) { if (c & 1) c = 0xEDB88320 ^ (c >>> 1); else c = c >>> 1; }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(data) {
  var crc = 0xFFFFFFFF;
  for (var i = 0; i < data.length; i++) crc = CRC32_TABLE[(crc ^ data[i]) & 0xFF] ^ (crc >>> 8);
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

function gzipStoredBlock(data) {
  var out = [0x1f, 0x8b, 0x08, 0x00];
  var ts = Math.floor(Date.now() / 1000);
  out.push(ts & 0xff, (ts >> 8) & 0xff, (ts >> 16) & 0xff, (ts >> 24) & 0xff);
  out.push(0x00, 0xff);
  var offset = 0;
  while (offset < data.length) {
    var chunk = data.slice(offset, Math.min(offset + 65535, data.length));
    var len = chunk.length; var isFinal = offset + len >= data.length ? 1 : 0;
    out.push(isFinal); out.push(len & 0xff, (len >> 8) & 0xff); out.push((~len) & 0xff, ((~len) >> 8) & 0xff);
    for (var i = 0; i < len; i++) out.push(chunk[i]);
    offset += len;
  }
  var crc = crc32(data);
  out.push(crc & 0xff, (crc >> 8) & 0xff, (crc >> 16) & 0xff, (crc >> 24) & 0xff);
  var size = data.length & 0xffffffff;
  out.push(size & 0xff, (size >> 8) & 0xff, (size >> 16) & 0xff, (size >> 24) & 0xff);
  return out;
}

// ==================== Key Derivation ====================

function deriveKey(requestId) {
  var keyBytes = utf8ToBytes(MASTER_KEY);
  var msgBytes = hexToBytes(String(requestId).replace(/-/g, ''));
  return hmacSha256(keyBytes, msgBytes);
}

// ==================== Body Encrypt/Decrypt ====================

function encryptBody(json, requestId) {
  var pt = utf8ToBytes(JSON.stringify(json));
  var gz = gzipStoredBlock(pt);
  var iv = randomBytes(16);
  var key = deriveKey(requestId);
  var ct = aesCbcEncrypt(pkcs7Pad(gz), key, iv);
  return iv.concat(ct);
}

function decryptBody(bodyBytes, requestId) {
  if (!bodyBytes || bodyBytes.length < 32) return null;
  // Check if it's plain JSON (not encrypted, e.g. error response)
  if (bodyBytes[0] === 0x7b || bodyBytes[0] === 0x5b) {
    try { return JSON.parse(bytesToUtf8(bodyBytes)); } catch(e) {}
  }
  if (bodyBytes.length % 16 !== 0) {
    try { return JSON.parse(bytesToUtf8(bodyBytes)); } catch(e) { return null; }
  }
  var iv = bodyBytes.slice(0, 16);
  var ct = bodyBytes.slice(16);
  var key = deriveKey(requestId);
  var pt = aesCbcDecrypt(ct, key, iv);
  try { if (pt.length > 0 && (pt[0] === 0x1f || (pt[0] & 0x0f) === 8)) pt = gunzipBytes(pt); } catch(e) {}
  try { return JSON.parse(bytesToUtf8(pt)); } catch(e) { return null; }
}

// ==================== Utility ====================

function generateUUID() {
  var e = Date.now(); var result = ""; var template = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
  for (var i = 0; i < template.length; i++) {
    var t = template.charAt(i);
    if (t === "x" || t === "y") { var r = (e + 16 * Math.random()) % 16 | 0; e = Math.floor(e / 16); result += (t === "x" ? r : (7 & r | 8)).toString(16); }
    else { result += t; }
  }
  return result;
}

function md5Hex(s) {
  function safeAdd(x,y){var lsw=(x&0xffff)+(y&0xffff);var msw=(x>>16)+(y>>16)+(lsw>>16);return(msw<<16)|(lsw&0xffff);}
  function bitRol(n,c){return(n<<c)|(n>>>(32-c));}
  function cmn(q,a,b,x,s,t){return safeAdd(bitRol(safeAdd(safeAdd(a,q),safeAdd(x,t)),s),b);}
  function ff(a,b,c,d,x,s,t){return cmn((b&c)|(~b&d),a,b,x,s,t);}
  function gg(a,b,c,d,x,s,t){return cmn((b&d)|(c&~d),a,b,x,s,t);}
  function hh(a,b,c,d,x,s,t){return cmn(b^c^d,a,b,x,s,t);}
  function ii(a,b,c,d,x,s,t){return cmn(c^(b|~d),a,b,x,s,t);}
  function binlMD5(x,len){
    x[len>>5]|=0x80<<(len%32);x[(((len+64)>>>9)<<4)+14]=len;
    var a=1732584193,b=-271733879,c=-1732584194,d=271733878;
    for(var i=0;i<x.length;i+=16){
      var oa=a,ob=b,oc=c,od=d;
      a=ff(a,b,c,d,x[i],7,-680876936);d=ff(d,a,b,c,x[i+1],12,-389564586);c=ff(c,d,a,b,x[i+2],17,606105819);b=ff(b,c,d,a,x[i+3],22,-1044525330);
      a=ff(a,b,c,d,x[i+4],7,-176418897);d=ff(d,a,b,c,x[i+5],12,1200080426);c=ff(c,d,a,b,x[i+6],17,-1473231341);b=ff(b,c,d,a,x[i+7],22,-45705983);
      a=ff(a,b,c,d,x[i+8],7,1770035416);d=ff(d,a,b,c,x[i+9],12,-1958414417);c=ff(c,d,a,b,x[i+10],17,-42063);b=ff(b,c,d,a,x[i+11],22,-1990404162);
      a=ff(a,b,c,d,x[i+12],7,1804603682);d=ff(d,a,b,c,x[i+13],12,-40341101);c=ff(c,d,a,b,x[i+14],17,-1502002290);b=ff(b,c,d,a,x[i+15],22,1236535329);
      a=gg(a,b,c,d,x[i+1],5,-165796510);d=gg(d,a,b,c,x[i+6],9,-1069501632);c=gg(c,d,a,b,x[i+11],14,643717713);b=gg(b,c,d,a,x[i],20,-373897302);
      a=gg(a,b,c,d,x[i+5],5,-701558691);d=gg(d,a,b,c,x[i+10],9,38016083);c=gg(c,d,a,b,x[i+15],14,-660478335);b=gg(b,c,d,a,x[i+4],20,-405537848);
      a=gg(a,b,c,d,x[i+9],5,568446438);d=gg(d,a,b,c,x[i+14],9,-1019803690);c=gg(c,d,a,b,x[i+3],14,-187363961);b=gg(b,c,d,a,x[i+8],20,1163531501);
      a=gg(a,b,c,d,x[i+13],5,-1444681467);d=gg(d,a,b,c,x[i+2],9,-51403784);c=gg(c,d,a,b,x[i+7],14,1735328473);b=gg(b,c,d,a,x[i+12],20,-1926607734);
      a=hh(a,b,c,d,x[i+5],4,-378558);d=hh(d,a,b,c,x[i+8],11,-2022574463);c=hh(c,d,a,b,x[i+11],16,1839030562);b=hh(b,c,d,a,x[i+14],23,-35309556);
      a=hh(a,b,c,d,x[i+1],4,-1530992060);d=hh(d,a,b,c,x[i+4],11,1272893353);c=hh(c,d,a,b,x[i+7],16,-155497632);b=hh(b,c,d,a,x[i+10],23,-1094730640);
      a=hh(a,b,c,d,x[i+13],4,681279174);d=hh(d,a,b,c,x[i],11,-358537222);c=hh(c,d,a,b,x[i+3],16,-722521979);b=hh(b,c,d,a,x[i+6],23,76029189);
      a=hh(a,b,c,d,x[i+9],4,-640364487);d=hh(d,a,b,c,x[i+12],11,-421815835);c=hh(c,d,a,b,x[i+15],16,530742520);b=hh(b,c,d,a,x[i+2],23,-995338651);
      a=ii(a,b,c,d,x[i],6,-198630844);d=ii(d,a,b,c,x[i+7],10,1126891415);c=ii(c,d,a,b,x[i+14],15,-1416354905);b=ii(b,c,d,a,x[i+5],21,-57434055);
      a=ii(a,b,c,d,x[i+12],6,1700485571);d=ii(d,a,b,c,x[i+3],10,-1894986606);c=ii(c,d,a,b,x[i+10],15,-1051523);b=ii(b,c,d,a,x[i+1],21,-2054922799);
      a=ii(a,b,c,d,x[i+8],6,1873313359);d=ii(d,a,b,c,x[i+15],10,-30611744);c=ii(c,d,a,b,x[i+6],15,-1560198380);b=ii(b,c,d,a,x[i+13],21,1309151649);
      a=ii(a,b,c,d,x[i+4],6,-145523070);d=ii(d,a,b,c,x[i+11],10,-1120210379);c=ii(c,d,a,b,x[i+2],15,718787259);b=ii(b,c,d,a,x[i+9],21,-343485551);
      a=safeAdd(a,oa);b=safeAdd(b,ob);c=safeAdd(c,oc);d=safeAdd(d,od);
    }
    return [a,b,c,d];
  }
  function binl2rstr(input){var out='';for(var i=0;i<input.length*32;i+=8)out+=String.fromCharCode((input[i>>5]>>>(i%32))&0xff);return out;}
  function rstr2binl(input){var out=[];out[(input.length>>2)-1]=undefined;for(var i=0;i<out.length;i++)out[i]=0;for(var i=0;i<input.length*8;i+=8)out[i>>5]|=(input.charCodeAt(i/8)&0xff)<<(i%32);return out;}
  function rstrMD5(s){return binl2rstr(binlMD5(rstr2binl(s),s.length*8));}
  function rstr2hex(input){var hex='0123456789abcdef';var out='';for(var i=0;i<input.length;i++){var x=input.charCodeAt(i);out+=hex.charAt((x>>>4)&0xf)+hex.charAt(x&0xf);}return out;}
  function str2rstrUTF8(input){return unescape(encodeURIComponent(input));}
  return rstr2hex(rstrMD5(str2rstrUTF8(String(s))));
}

// Bytes <-> ArrayBuffer conversion
function bytesToArrayBuffer(bytes) {
  var buf = new ArrayBuffer(bytes.length);
  var view = new Uint8Array(buf);
  for (var i = 0; i < bytes.length; i++) view[i] = bytes[i];
  return buf;
}

function arrayBufferToBytes(buf) {
  if (!buf) return [];
  var view;
  try { view = new Uint8Array(buf); } catch(e) { return []; }
  var bytes = [];
  for (var i = 0; i < view.length; i++) bytes.push(view[i]);
  return bytes;
}

// ==================== HTTP Transport ====================
//
// 传输策略（优先级从高到低）：
// 1. fetch() — 原生支持 ArrayBuffer body，发送原始二进制字节
//    → 在 forwardplayer.com/develop/ 在线工具中可用（Node.js 环境）
// 2. XMLHttpRequest — xhr.send(ArrayBuffer) 发送原始二进制
//    → 在浏览器环境中可用
// 3. Widget.http.post — base64 字符串 body + base64Data:true（仅用于响应）
//    → 纯 ASCII base64 不受 UTF-8 编码影响
//    → 但服务端无法解码 base64 body → 返回 2001 解密失败
//    → 仅用于诊断（确认网络可达但无法发送二进制）
//
// 核心问题（widget-adaptor.ts 源码确认）：
//   fetchOptions.body = typeof body === 'string' ? body : JSON.stringify(body);
//   → 非 string body（ArrayBuffer/Uint8Array）被 JSON.stringify → "{}"
//   → string body 中的字节 >= 0x80 被 UTF-8 多字节编码 → 二进制损坏
//   → 结论：Widget.http.post 无法发送二进制数据

// 方案1: fetch() — 发送 ArrayBuffer body（原始二进制）
function fetchPost(url, bodyArrayBuffer, headers, requestId) {
  return fetch(url, {
    method: "POST",
    headers: headers,
    body: bodyArrayBuffer
  }).then(function(response) {
    // 服务端即使出错也返回 200（错误信息在加密响应体内）
    return response.arrayBuffer();
  }).then(function(buffer) {
    var bytes = arrayBufferToBytes(buffer);
    if (!bytes || bytes.length === 0) return null;
    if (bytes[0] === 0x7b || bytes[0] === 0x5b) {
      try { return JSON.parse(bytesToUtf8(bytes)); } catch(e) {}
    }
    return decryptBody(bytes, requestId);
  });
}

// 方案2: XMLHttpRequest — send(ArrayBuffer)
function xhrPost(url, bodyArrayBuffer, headers, requestId) {
  return new Promise(function(resolve, reject) {
    var xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.responseType = "arraybuffer";
    xhr.timeout = 20000;

    if (headers) {
      for (var key in headers) {
        try { xhr.setRequestHeader(key, headers[key]); } catch(e) {}
      }
    }

    xhr.onload = function() {
      var response = xhr.response;
      var bytes = null;

      if (response instanceof ArrayBuffer) {
        bytes = arrayBufferToBytes(response);
      } else if (typeof Uint8Array !== "undefined" && response instanceof Uint8Array) {
        bytes = Array.prototype.slice.call(response);
      } else if (typeof response === "string") {
        if (response.charCodeAt(0) === 0x7b || response.charCodeAt(0) === 0x5b) {
          try { resolve(JSON.parse(response)); return; } catch(e) {}
        }
        bytes = [];
        for (var i = 0; i < response.length; i++) bytes.push(response.charCodeAt(i) & 0xff);
      } else if (response && response.byteLength) {
        bytes = arrayBufferToBytes(response);
      }

      if (!bytes || bytes.length === 0) { resolve(null); return; }
      if (bytes[0] === 0x7b || bytes[0] === 0x5b) {
        try { resolve(JSON.parse(bytesToUtf8(bytes))); return; } catch(e) {}
      }
      resolve(decryptBody(bytes, requestId));
    };

    xhr.onerror = function() { reject(new Error("Network error (XHR)")); };
    xhr.ontimeout = function() { reject(new Error("Request timeout (XHR)")); };
    xhr.send(bodyArrayBuffer);
  });
}

// 方案3: Widget.http.post — base64 body + base64Data:true（诊断用）
function widgetPost(url, bodyArrayBuffer, headers, requestId) {
  var bytes = arrayBufferToBytes(bodyArrayBuffer);
  var b64Str = bytesToBase64(bytes);
  return Widget.http.post(url, b64Str, {
    headers: headers,
    base64Data: true
  }).then(function(res) {
    if (!res) return null;
    var data = res.data;
    if (data == null) return null;

    var respBytes = null;

    if (data instanceof ArrayBuffer) {
      respBytes = arrayBufferToBytes(data);
    } else if (typeof Uint8Array !== "undefined" && data instanceof Uint8Array) {
      respBytes = Array.prototype.slice.call(data);
    } else if (typeof data === "string") {
      // base64Data:true → data 是 base64 编码的二进制
      if (data.length > 0 && (data.charCodeAt(0) === 0x7b || data.charCodeAt(0) === 0x5b)) {
        try { return JSON.parse(data); } catch(e) {}
      }
      try { respBytes = base64ToBytes(data); } catch(e2) {}
      if (!respBytes || respBytes.length === 0) {
        respBytes = [];
        for (var i = 0; i < data.length; i++) respBytes.push(data.charCodeAt(i) & 0xff);
      }
    } else if (data && data.byteLength) {
      respBytes = arrayBufferToBytes(data);
    } else {
      return data;
    }

    if (!respBytes || respBytes.length === 0) return null;
    if (respBytes[0] === 0x7b || respBytes[0] === 0x5b) {
      try { return JSON.parse(bytesToUtf8(respBytes)); } catch(e) {}
    }
    return decryptBody(respBytes, requestId);
  });
}

// 方案4: Cloudflare Worker 代理 — 通过 Worker 中继二进制数据
// 模块将加密二进制 body 编码为 base64，通过 Widget.http.post 发送 JSON 到 Worker
// Worker 解码 base64 → 二进制，转发到 API 服务器，返回 base64 编码的响应
// 全程只收发 ASCII（JSON + base64），完全绕过 Widget.http.post 的二进制限制
function workerPost(proxyUrl, targetUrl, bodyArrayBuffer, headers, requestId) {
  var bodyBytes = arrayBufferToBytes(bodyArrayBuffer);
  var bodyB64 = bytesToBase64(bodyBytes);

  // 构造 Worker 请求 JSON（纯 ASCII，安全通过 Widget.http.post）
  var proxyPayload = JSON.stringify({
    url: targetUrl,
    body_b64: bodyB64,
    headers: headers
  });

  return Widget.http.post(proxyUrl, proxyPayload, {
    headers: { "Content-Type": "application/json" }
  }).then(function(res) {
    if (!res || !res.data) return null;

    var data = res.data;
    var parsed = null;

    // 解析 Worker 响应 JSON
    if (typeof data === "string") {
      try { parsed = JSON.parse(data); } catch(e) { return null; }
    } else if (typeof data === "object" && data !== null) {
      parsed = data;
    }

    if (!parsed || !parsed.body_b64) return null;

    // 解码 base64 响应 → 二进制
    var respBytes = base64ToBytes(parsed.body_b64);
    if (!respBytes || respBytes.length === 0) return null;

    // 检查是否为明文 JSON（错误响应）
    if (respBytes[0] === 0x7b || respBytes[0] === 0x5b) {
      try { return JSON.parse(bytesToUtf8(respBytes)); } catch(e) {}
    }

    // 解密响应
    return decryptBody(respBytes, requestId);
  });
}

// 检测可用的传输方式（优先级：fetch > XHR > Worker代理 > Widget直连）
function detectTransport() {
  if (typeof fetch !== "undefined") return "fetch";
  if (typeof XMLHttpRequest !== "undefined") return "xhr";
  if (_proxyUrl && typeof Widget !== "undefined" && Widget.http && Widget.http.post) return "worker";
  if (typeof Widget !== "undefined" && Widget.http && Widget.http.post) return "widget";
  return "none";
}

// 发送单个请求（指定传输方式）
function sendRequest(url, bodyArrayBuffer, headers, requestId, transport) {
  if (transport === "fetch") {
    return fetchPost(url, bodyArrayBuffer, headers, requestId);
  } else if (transport === "xhr") {
    return xhrPost(url, bodyArrayBuffer, headers, requestId);
  } else if (transport === "worker") {
    return workerPost(_proxyUrl, url, bodyArrayBuffer, headers, requestId);
  } else if (transport === "widget") {
    return widgetPost(url, bodyArrayBuffer, headers, requestId);
  }
  return Promise.reject(new Error("No HTTP transport available"));
}

// ==================== API Client ====================

function getDeviceId() {
  if (_deviceId) return _deviceId;
  _deviceId = generateUUID().toLowerCase();
  return _deviceId;
}

/**
 * 发送 API 请求（多线路容错 + 自动传输方式检测）
 * 传输优先级：fetch > XMLHttpRequest > Widget.http.post
 * 主线路失败自动切换备用线路，会话过期(2002)自动重登
 */
function apiRequest(path, data) {
  var sessionId = generateUUID().replace(/-/g, "");
  var inner = { token: "", deviceId: getDeviceId(), data: data };
  if (_loginState && _loginState.token) {
    inner.token = _loginState.token + "_" + _loginState.userId;
  }

  var transport = detectTransport();
  if (transport === "none") {
    return Promise.reject(new Error("无可用 HTTP 传输方式（fetch/XMLHttpRequest/Widget.http.post 均不可用）"));
  }

  // 排序线路：首选线路排前面
  var orderedLines = [];
  for (var i = 0; i < LINES.length; i++) {
    if (LINES[i].base === _preferredLine) {
      orderedLines.unshift(LINES[i]);
    } else {
      orderedLines.push(LINES[i]);
    }
  }

  var maxAttempts = Math.min(3, orderedLines.length);
  var attempt = 0;

  function tryNextLine() {
    if (attempt >= maxAttempts) {
      return Promise.reject(new Error("所有线路均不可用 (传输: " + transport + ")"));
    }
    var line = orderedLines[attempt];
    attempt++;
    var url = line.base + "/api" + path;
    var requestId = generateUUID().toLowerCase();
    var bodyBytes = encryptBody(inner, requestId);
    var bodyArrayBuffer = bytesToArrayBuffer(bodyBytes);

    var t = Math.floor(Date.now() / 1000);
    var urlClean = url.replace(/^https?:\/\//, "");
    var signSource = "Dart|" + sessionId + "|" + requestId + "|" + t + "|" + urlClean;
    var sign = md5Hex(signSource);

    var headers = {
      "version": "1.0.0",
      "deviceType": "web",
      "time": String(t),
      "sign": sign + "-" + t,
      "requestId": requestId,
      "sessionId": sessionId,
      "deviceBrand": "",
      "deviceModel": "",
      "systemName": "",
      "systemVersion": "",
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": UA
    };

    return sendRequest(url, bodyArrayBuffer, headers, requestId, transport)
      .then(function(result) {
        if (result) {
          _preferredLine = line.base;
          // 2002: 会话过期 → 清除登录并重试
          if (result.status === "n" && (result.errorCode === 2002 || result.error === "2002")) {
            _loginState = null;
            return ensureLogin().then(function() {
              return apiRequest(path, data);
            });
          }
          return result;
        }
        // 结果为 null → 尝试下一线路
        if (attempt < maxAttempts) return tryNextLine();
        return null;
      })
      .catch(function(e) {
        // 当前线路失败 → 尝试下一线路
        if (attempt < maxAttempts) return tryNextLine();
        throw e;
      });
  }

  return tryNextLine();
}

function ensureLogin() {
  if (_loginState && _loginState.token) return Promise.resolve(_loginState);
  return apiRequest("/login/device", {
    line_code: "china_1",
    channel_code: "",
    share_code: "",
    clipboard_text: "",
    device_info: {
      browserName: "BrowserName.safari",
      language: "zh-CN",
      userAgent: UA,
      platform: "iPhone"
    }
  }).then(function(result) {
    if (result && result.data) {
      _loginState = {
        userId: String(result.data.user_id),
        token: result.data.token
      };
      return _loginState;
    }
    throw new Error("Login failed: " + JSON.stringify(result));
  });
}

// ==================== API Wrappers ====================

function fetchNavList() {
  return ensureLogin().then(function() {
    return apiRequest("/drama/navList", {});
  });
}

// 分类名称 → 分类代码映射（枚举值 → API 真实 code）
// 从 /drama/navList API 动态获取，确保新增分类（综艺/黑料/国产传媒等）也能正确请求
var _navListCache = null;
function fetchNavListCached() {
  if (_navListCache) return Promise.resolve(_navListCache);
  return fetchNavList().then(function(result) {
    // API 返回 { status, data: { list: [...] } }，缓存 data 部分
    if (result && result.data && result.data.list) {
      _navListCache = result.data;
    } else if (result && result.list) {
      _navListCache = result;
    }
    return _navListCache;
  }).catch(function() { return null; });
}

// 将枚举分类值（如 "zongyi"）解析为 API 真实分类代码
// 策略：先查 navList 的 code 字段精确匹配；若无匹配，查 name 字段模糊匹配
function resolveCategoryCode(enumValue) {
  // 枚举值 → 中文名 映射（用于 name 模糊匹配 fallback）
  var nameMap = {
    "yuandou": "黄豆原创",
    "aiman": "AI漫剧",
    "erciyuan": "二次元",
    "caibian": "擦边",
    "zhenren": "真人",
    "zongyi": "综艺",
    "heiliao": "黑料",
    "guochuanmei": "国产传媒"
  };

  return fetchNavListCached().then(function(navResult) {
    // API 返回结构可能是 { list: [...] } 或 { data: { list: [...] } }
    var list = null;
    if (navResult && navResult.list) list = navResult.list;
    else if (navResult && navResult.data && navResult.data.list) list = navResult.data.list;
    if (!list) return enumValue;

    // 1) 精确匹配 code
    for (var i = 0; i < list.length; i++) {
      if (str(list[i].code) === enumValue) return enumValue;
    }

    // 2) 用中文名模糊匹配 name 字段
    var cnName = nameMap[enumValue] || "";
    if (cnName) {
      for (var i = 0; i < list.length; i++) {
        var apiName = str(list[i].name);
        if (apiName && (apiName.indexOf(cnName) >= 0 || cnName.indexOf(apiName) >= 0)) {
          return str(list[i].code) || enumValue;
        }
      }
    }

    // 3) 无匹配，返回原值（API 可能仍能处理）
    return enumValue;
  });
}

function fetchNavFilter(code) {
  return ensureLogin().then(function() {
    return apiRequest("/drama/navFilter", { code: code });
  });
}

function fetchNavBlock(code, tab, page) {
  return ensureLogin().then(function() {
    return apiRequest("/drama/navBlock", { code: code, tab: tab, page: String(page) });
  });
}

function fetchDramaList(page, keywords, catId) {
  return ensureLogin().then(function() {
    var params = { page: String(page), page_size: "30" };
    if (keywords) params.keywords = keywords;
    if (catId) params.cat_id = catId;
    return apiRequest("/drama/list", params);
  });
}

function fetchDramaDetail(id) {
  return ensureLogin().then(function() {
    return apiRequest("/drama/detail", { id: id });
  });
}

// 调用 /drama/play API 获取播放地址（主线路）
// Scripting App 的 rawPlay 方法：发送 { id, seq } 获取 m3u8 URL
function fetchPlayUrl(id, seq) {
  return ensureLogin().then(function() {
    return apiRequest("/drama/play", { id: id, seq: String(seq) });
  });
}

// ==================== Helper Functions ====================

function str(v, def) { return v != null ? String(v) : (def || ""); }
function num(v, def) { var n = Number(v); return isNaN(n) ? (def || 0) : n; }

function absCover(url) {
  if (!url) return "";
  if (url.indexOf("http") === 0) return url;
  if (url.indexOf("//") === 0) return "https:" + url;
  return url;
}

/**
 * 构造直接 m3u8 播放 URL（无需 VIP 解锁）
 * 从 proxy.ts buildDirectM3u8 移植：{base}/api/drama/hls/{dramaId}/{seq}/play.m3u8?line=free
 * 该 URL 已验证无鉴权（proxy.ts 付费集直连逻辑）
 */
function constructM3u8Url(dramaId, seq, baseUrl) {
  var base = baseUrl || _preferredLine;
  return base + "/api/drama/hls/" + dramaId + "/" + seq + "/play.m3u8?line=free";
}

function playbackHeaders(baseUrl) {
  var base = baseUrl || _preferredLine;
  // 与 proxy.ts 一致：仅 UA + Accept
  // 不发 Origin（会触发 CloudFront CORS preflight 导致挂起）
  // 不发 Referer（proxy.ts HLS 拉取也不发 Referer）
  return {
    "User-Agent": UA,
    "Accept": "*/*"
  };
}

function parseDramaItem(item) {
  if (!item) return null;
  var dramaId = str(item.id) || str(item.drama_id).replace(/^[^_]+_/, "");
  if (!dramaId) return null;
  var cover = absCover(str(item.img_y || item.img || item.cover || item.img_x));
  var descParts = [];
  var epCount = 0;
  if (item.category) descParts.push(str(item.category));
  if (item.episode_count) {
    epCount = parseInt(item.episode_count, 10) || 0;
    descParts.push(str(item.episode_count) + "集");
  }
  if (item.corner) descParts.push(str(item.corner));
  if (item.hot_rate) descParts.push("热度" + str(item.hot_rate));
  if (item.update_label) descParts.push(str(item.update_label));

  // link 编码格式: huangdou:{dramaId}~{episodeCount}
  // 使用 ~ 而非 #，因为 Forward App 会把 # 当作 URL fragment 截断
  // episodeCount 用于 loadDetail API 失败时的 fallback 集数
  var linkVal = "huangdou:" + dramaId;
  if (epCount > 0) linkVal += "~" + epCount;

  return {
    id: "huangdou:" + dramaId,
    type: "url",
    title: str(item.name),
    posterPath: cover,
    backdropPath: cover,
    coverUrl: cover,
    description: descParts.filter(Boolean).join(" · "),
    link: linkVal
  };
}

function extractDramasFromNavBlock(result) {
  if (!result || !result.data || !result.data.list) return [];
  var all = [];
  var blocks = result.data.list;
  for (var i = 0; i < blocks.length; i++) {
    var items = blocks[i].items || blocks[i].dramas || [];
    if (Array.isArray(items)) {
      for (var j = 0; j < items.length; j++) {
        var parsed = parseDramaItem(items[j]);
        if (parsed) all.push(parsed);
      }
    }
  }
  return all;
}

function extractDramasFromList(result) {
  if (!result || !result.data || !result.data.list) return [];
  var all = [];
  var items = result.data.list;
  for (var i = 0; i < items.length; i++) {
    if (items[i].items) {
      for (var j = 0; j < items[i].items.length; j++) {
        var p = parseDramaItem(items[i].items[j]);
        if (p) all.push(p);
      }
    } else {
      var parsed = parseDramaItem(items[i]);
      if (parsed) all.push(parsed);
    }
  }
  return all;
}

// ==================== Module Functions ====================

async function loadList(params) {
  initConfig(params);
  var category = str(params.category, "yuandou");
  var page = num(params.page, 1);
  if (page < 1) page = 1;

  try {
    // 0) 先从 navList 获取真实分类代码（处理综艺/黑料/国产传媒等新增分类）
    var realCode = await resolveCategoryCode(category);

    // 1) 获取分类导航过滤器（使用真实 code）
    var filterResult = await fetchNavFilter(realCode);
    var tabs = [];
    if (filterResult && filterResult.data && filterResult.data.list) {
      tabs = filterResult.data.list;
    }

    var items = [];

    if (tabs.length > 0 && tabs[0].tab) {
      // 2a) 分类有 tab 值（如 yuandou → tab=recommend）
      // 使用 navBlock API 返回 blocks with nested items
      var result = await fetchNavBlock(realCode, tabs[0].tab, page);
      items = extractDramasFromNavBlock(result);

      // 黄豆原创推荐 tab 无数据时，补充搜索
      if (items.length === 0 && realCode === "yuandou" && page === 1) {
        var searchResult = await fetchDramaList(1, "黄豆原创");
        items = extractDramasFromList(searchResult);
      }
    } else if (tabs.length > 0 && tabs[0].filter && tabs[0].filter.cat_id) {
      // 2b) 分类有 cat_id 过滤（如 aiman → cat_id=1050902）
      var result2 = await fetchDramaList(page, null, tabs[0].filter.cat_id);
      items = extractDramasFromList(result2);
    } else {
      // 2c) 回退：搜索分类名
      var categoryName = "";
      var catMap = {
        "yuandou": "黄豆原创",
        "aiman": "AI漫剧",
        "erciyuan": "二次元",
        "caibian": "擦边短剧",
        "zhenren": "真人短剧",
        "zongyi": "综艺",
        "heiliao": "黑料",
        "guochuanmei": "国产传媒"
      };
      categoryName = catMap[category] || category;
      var result3 = await fetchDramaList(page, categoryName);
      items = extractDramasFromList(result3);
    }

    if (items.length === 0) {
      return [{
        id: "huangdou:empty",
        type: "url",
        title: "暂无短剧",
        description: "当前分类没有返回短剧，请尝试其他分类或搜索",
        coverUrl: undefined,
        link: "huangdou:empty"
      }];
    }

    return items;
  } catch (e) {
    return [{
      id: "huangdou:error",
      type: "url",
      title: "加载失败",
      description: "黄豆短剧加载失败: " + (e.message || String(e)),
      coverUrl: undefined,
      link: "huangdou:error"
    }];
  }
}

async function search(params) {
  initConfig(params);
  var keyword = str(params.keyword, "").trim();
  var page = num(params.page, 1);
  if (page < 1) page = 1;

  if (!keyword) {
    return [{
      id: "huangdou:searchhint",
      type: "url",
      title: "请输入搜索关键词",
      description: "在上方输入框输入短剧名称",
      coverUrl: undefined,
      link: "huangdou:searchhint"
    }];
  }

  try {
    var result = await fetchDramaList(page, keyword);
    if (!result || !result.data || !result.data.list) {
      return [{
        id: "huangdou:noresult",
        type: "url",
        title: "未找到短剧",
        description: "没有找到\"" + keyword + "\"相关的短剧",
        coverUrl: undefined,
        link: "huangdou:noresult"
      }];
    }

    var items = extractDramasFromList(result);
    if (items.length === 0) {
      return [{
        id: "huangdou:noresult",
        type: "url",
        title: "未找到短剧",
        description: "没有找到\"" + keyword + "\"相关的短剧",
        coverUrl: undefined,
        link: "huangdou:noresult"
      }];
    }
    return items;
  } catch (e) {
    return [{
      id: "huangdou:error",
      type: "url",
      title: "搜索失败",
      description: "搜索失败: " + (e.message || String(e)),
      coverUrl: undefined,
      link: "huangdou:error"
    }];
  }
}

async function loadResource(params) {
  initConfig(params);

  // 防御性参数处理
  var link = "";
  var seqFromParam = "";
  if (typeof params === "string") {
    link = params;
  } else if (params) {
    if (params.link) link = String(params.link);
    if (params.episode) seqFromParam = String(params.episode);
  }

  // 跨模块调用检测：如果 Forward App 传了 seriesName（其他模块的播放请求），
  // 但 link 不是 huangdou: 前缀，说明是别的模块在调用 → 返回空，防止跨模块干扰
  if (params && typeof params === "object" && params.seriesName) {
    if (!link || link.indexOf("huangdou:") !== 0) return [];
  }

  // 空链接 → 空
  if (!link) return [];

  // 白名单：只处理 huangdou: 前缀的链接（彻底防止跨模块干扰）
  if (link.indexOf("huangdou:") !== 0) return [];

  // 占位链接 → 空
  if (link === "huangdou:error" || link === "huangdou:empty" ||
      link === "huangdou:searchhint" || link === "huangdou:noresult") {
    return [];
  }

  // 去掉 huangdou: 前缀
  var rawLink = link.substring("huangdou:".length);

  // 去掉 ~episodeCount 后缀（parseDramaItem 编码的集数信息）
  var tildeIdx = rawLink.indexOf("~");
  if (tildeIdx >= 0) {
    rawLink = rawLink.substring(0, tildeIdx);
  }

  // 解析 dramaId 和 seq
  var seq = seqFromParam || "1";
  var dramaId = rawLink;

  // 解析 |seq（如果 link 里有 |seq，优先用 link 里的）
  var resPipeIdx = dramaId.indexOf("|");
  if (resPipeIdx >= 0) {
    seq = dramaId.substring(resPipeIdx + 1);
    dramaId = dramaId.substring(0, resPipeIdx);
  }

  if (!dramaId) return [];

  // 验证 seq 为数字
  if (!/^\d+$/.test(seq)) seq = "1";

  // 返回多线路播放源（play.m3u8?line=free 无鉴权）
  var resources = [];
  var maxLines = Math.min(4, LINES.length);
  for (var i = 0; i < maxLines; i++) {
    var base = LINES[i].base;
    resources.push({
      name: "线路" + (i + 1),
      description: "黄豆短剧 第" + seq + "集",
      url: base + "/api/drama/hls/" + dramaId + "/" + seq + "/play.m3u8?line=free",
      customHeaders: { "User-Agent": UA, "Accept": "*/*" }
    });
  }

  return resources;
}

async function loadDetail(link) {
  if (!link) return null;
  var linkStr = String(link);

  // 白名单：只处理 huangdou: 前缀的链接
  if (linkStr.indexOf("huangdou:") !== 0) return null;

  // 占位链接 → null
  if (linkStr === "huangdou:error" || linkStr === "huangdou:empty" ||
      linkStr === "huangdou:searchhint" || linkStr === "huangdou:noresult") {
    return null;
  }

  // 去掉 huangdou: 前缀
  var rawLink = linkStr.substring("huangdou:".length);

  // 提取 ~episodeCount（parseDramaItem 编码的集数信息）
  // 使用 ~ 而非 #，因为 Forward App 会把 # 当作 URL fragment 截断
  var fallbackEpCount = 0;
  var tildeIdx = rawLink.indexOf("~");
  if (tildeIdx >= 0) {
    fallbackEpCount = parseInt(rawLink.substring(tildeIdx + 1), 10) || 0;
    rawLink = rawLink.substring(0, tildeIdx);
  }

  // 集数链接处理：rawLink 格式 "dramaId|seq" → 返回单集视频项
  var epPipeIdx = rawLink.indexOf("|");
  if (epPipeIdx >= 0) {
    var epDramaId = rawLink.substring(0, epPipeIdx);
    var epSeqStr = rawLink.substring(epPipeIdx + 1);
    if (epDramaId && epSeqStr && /^\d+$/.test(epSeqStr)) {
      var epM3u8 = constructM3u8Url(epDramaId, epSeqStr);
      var epSources = [];
      var epMaxLines = Math.min(4, LINES.length);
      for (var ei = 0; ei < epMaxLines; ei++) {
        epSources.push({ url: LINES[ei].base + "/api/drama/hls/" + epDramaId + "/" + epSeqStr + "/play.m3u8?line=free", type: "application/x-mpegURL", label: "线路" + (ei + 1) });
      }
      return {
        id: linkStr,
        type: "video",
        title: "第" + epSeqStr + "集",
        link: linkStr,
        videoUrl: epM3u8,
        videoSources: epSources,
        customHeaders: { "User-Agent": UA, "Accept": "*/*" }
      };
    }
  }

  // 主详情页
  var dramaId = rawLink;
  if (!dramaId) return null;

  var title = "";
  var description = "";
  var coverUrl = "";
  var episodeItems = [];

  // 构建多线路 videoSources（每集都有，用户可切换线路）
  function buildEpVideoSources(dramaId, seq) {
    var sources = [];
    var maxLines = Math.min(4, LINES.length);
    for (var k = 0; k < maxLines; k++) {
      sources.push({
        url: LINES[k].base + "/api/drama/hls/" + dramaId + "/" + seq + "/play.m3u8?line=free",
        type: "application/x-mpegURL",
        label: "线路" + (k + 1)
      });
    }
    return sources;
  }

  // 尝试 API 获取真实集数
  try {
    var detail = await fetchDramaDetail(dramaId);
    if (detail && detail.data) {
      title = str(detail.data.name, "");
      description = str(detail.data.description, "");
      coverUrl = absCover(str(detail.data.img_y || detail.data.img || detail.data.cover || detail.data.img_x));

      var rawEpisodes = detail.data.episodes || [];
      for (var i = 0; i < rawEpisodes.length; i++) {
        var ep = rawEpisodes[i];
        var seq = num(ep.seq, i + 1);
        var epName = str(ep.name, "第" + seq + "集");
        var epType = str(ep.type, "free");
        if (epType !== "free") epName += " [VIP]";
        var epM3u8 = constructM3u8Url(dramaId, seq);
        episodeItems.push({
          id: "huangdou:" + dramaId + ":" + seq,
          type: "url",
          title: epName,
          link: "huangdou:" + dramaId + "|" + seq,
          videoUrl: epM3u8,
          videoSources: buildEpVideoSources(dramaId, seq)
        });
      }
    }
  } catch(e) {
    // API 失败，使用 fallback
  }

  // Fallback：API 没拿到集数 → 用 link 中编码的集数，或默认 30 集
  if (episodeItems.length === 0) {
    var epCount = fallbackEpCount > 0 ? fallbackEpCount : 30;
    for (var i = 1; i <= epCount; i++) {
      var fbM3u8 = constructM3u8Url(dramaId, i);
      episodeItems.push({
        id: "huangdou:" + dramaId + ":" + i,
        type: "url",
        title: "第" + i + "集",
        link: "huangdou:" + dramaId + "|" + i,
        videoUrl: fbM3u8,
        videoSources: buildEpVideoSources(dramaId, i)
      });
    }
  }

  // videoUrl 设为第1集 m3u8 地址
  var mainVideoUrl = constructM3u8Url(dramaId, 1);

  // 主详情页也提供多线路
  var mainSources = [];
  var mainMaxLines = Math.min(4, LINES.length);
  for (var mi = 0; mi < mainMaxLines; mi++) {
    mainSources.push({ url: LINES[mi].base + "/api/drama/hls/" + dramaId + "/1/play.m3u8?line=free", type: "application/x-mpegURL", label: "线路" + (mi + 1) });
  }

  var result = {
    id: "huangdou:" + dramaId,
    type: "url",
    title: title || ("黄豆短剧 " + dramaId),
    link: "huangdou:" + dramaId,
    description: description || ("黄豆短剧 " + dramaId),
    videoUrl: mainVideoUrl,
    videoSources: mainSources,
    episodeItems: episodeItems.length > 0 ? episodeItems : undefined,
    customHeaders: { "User-Agent": UA, "Accept": "*/*" }
  };

  if (coverUrl) {
    result.posterPath = coverUrl;
    result.backdropPath = coverUrl;
    result.coverUrl = coverUrl;
  }

  return result;
}
