import { useEffect, useState } from 'react'
import type { CoreConnection } from '../types'

/** Subskrybuje stan połączenia z backendem (z procesu głównego Electron). */
export function useConnection(): CoreConnection {
  const [conn, setConn] = useState<CoreConnection>({ status: 'starting' })
  useEffect(() => {
    void window.caelo.getCore().then(setConn)
    const unsubscribe = window.caelo.onCoreStatus(setConn)
    return unsubscribe
  }, [])
  return conn
}
