import { useEffect, useRef, useState } from 'react'

type OnMessageFn = (data: any) => void

export default function useSSE(url?: string, onMessage?: OnMessageFn) {
  const esRef = useRef<EventSource | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastRaw, setLastRaw] = useState<string | null>(null)
  const [eventLog, setEventLog] = useState<Array<{ t: string; data: string }>>([])
  const backoffRef = useRef(500)
  const closedByUser = useRef(false)

  useEffect(() => {
    if (!url) return
    closedByUser.current = false

    const connect = () => {
      try {
        const es = new EventSource(url)
        esRef.current = es
        es.addEventListener('open', () => {
          setConnected(true)
          backoffRef.current = 500
        })

        const handle = (type: string, ev: MessageEvent) => {
          const text = ev.data
          setLastRaw(text)
          setEventLog((l) => [{ t: type, data: text }, ...l].slice(0, 100))
          try {
            const parsed = JSON.parse(text)
            onMessage && onMessage(parsed)
          } catch (e) {
            // ignore parse errors
          }
        }

        es.addEventListener('update', (ev) => handle('update', ev as MessageEvent))
        es.addEventListener('message', (ev) => handle('message', ev as MessageEvent))
        es.addEventListener('error', () => {
          setConnected(false)
          if (esRef.current) esRef.current.close()
          esRef.current = null
          if (!closedByUser.current) {
            const timeout = backoffRef.current
            backoffRef.current = Math.min(10_000, backoffRef.current * 1.5)
            setTimeout(() => connect(), timeout)
          }
        })
      } catch (e) {
        setConnected(false)
        const timeout = backoffRef.current
        backoffRef.current = Math.min(10_000, backoffRef.current * 1.5)
        setTimeout(() => connect(), timeout)
      }
    }

    connect()

    return () => {
      closedByUser.current = true
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
  }, [url, onMessage])

  const close = () => {
    closedByUser.current = true
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setConnected(false)
  }

  return { connected, lastRaw, eventLog, close }
}
