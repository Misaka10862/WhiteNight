import extract from 'png-chunks-extract'
import encode from 'png-chunks-encode'
import pngText from 'png-chunk-text'
import type { CharacterCard } from './api'

function decodeBase64Utf8(value: string): string {
  const bytes = Uint8Array.from(atob(value), (char) => char.charCodeAt(0))
  return new TextDecoder().decode(bytes)
}

function encodeBase64Utf8(value: string): string {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

export async function readCharacterPng(file: File): Promise<CharacterCard> {
  const chunks = extract(new Uint8Array(await file.arrayBuffer()))
  const metadata = chunks
    .filter((chunk) => chunk.name === 'tEXt')
    .map((chunk) => pngText.decode(chunk.data))
  const selected = metadata.find((item) => item.keyword.toLowerCase() === 'ccv3')
    ?? metadata.find((item) => item.keyword.toLowerCase() === 'chara')
  if (!selected) throw new Error('PNG 中没有 ccv3/chara 角色卡元数据')
  return JSON.parse(decodeBase64Utf8(selected.text)) as CharacterCard
}

export async function writeCharacterPng(
  avatarDataUrl: string,
  card: CharacterCard,
): Promise<Blob> {
  const comma = avatarDataUrl.indexOf(',')
  if (comma < 0) throw new Error('头像不是有效 data URL')
  const image = Uint8Array.from(atob(avatarDataUrl.slice(comma + 1)), (char) => char.charCodeAt(0))
  const chunks = extract(image).filter((chunk) => {
    if (chunk.name !== 'tEXt') return true
    const keyword = pngText.decode(chunk.data).keyword.toLowerCase()
    return keyword !== 'chara' && keyword !== 'ccv3'
  })
  const v2 = { ...card, spec: 'chara_card_v2' as const, spec_version: '2.0' }
  const v3 = { ...card, spec: 'chara_card_v3' as const, spec_version: '3.0' }
  chunks.splice(-1, 0,
    pngText.encode('chara', encodeBase64Utf8(JSON.stringify(v2))),
    pngText.encode('ccv3', encodeBase64Utf8(JSON.stringify(v3))),
  )
  return new Blob([encode(chunks) as Uint8Array<ArrayBuffer>], { type: 'image/png' })
}

export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}
