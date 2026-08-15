export interface StatusResponse {
  name: string
  version: string
  env: string
  host: string
  port: number
  database: {
    url_backend: 'sqlite' | 'sqlcipher'
    reachable: boolean
  }
}

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetch('/api/v1/status')
  if (!response.ok) {
    throw new Error(`status request failed: ${response.status}`)
  }
  return (await response.json()) as StatusResponse
}
