/// <reference types="vite/client" />

declare module 'png-chunks-extract' {
  export default function extract(data: Uint8Array): Array<{ name: string; data: Uint8Array }>
}
declare module 'png-chunks-encode' {
  export default function encode(chunks: Array<{ name: string; data: Uint8Array }>): Uint8Array
}
declare module 'png-chunk-text' {
  const text: {
    encode(keyword: string, value: string): { name: string; data: Uint8Array }
    decode(data: Uint8Array): { keyword: string; text: string }
  }
  export default text
}
