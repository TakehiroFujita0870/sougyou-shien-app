import { useRef, useState } from 'react';
import { LocalDashboardShell } from './LocalDashboardShell';
import { LocalHomeSurface } from './LocalHomeSurface';
import { LocalGraphSurface } from './LocalGraphSurface';
import { LocalControlDashboard } from './LocalControlDashboard';
import { createLocalDashboardClient } from '../runtime/localDashboardClient';

/** Current three-screen app: no legacy workspace initialization or storage writes. */
export function LocalDashboardApp() {
  const [page, setPage] = useState('local-home');
  const client = useRef(null);
  if (!client.current) client.current = createLocalDashboardClient();
  const openServices = () => setPage('local-services');
  return <LocalDashboardShell activePage={page} onSelect={setPage}>
    {page === 'graph' ? <LocalGraphSurface client={client.current} onOpenServices={openServices} />
      : page === 'local-services' ? <LocalControlDashboard client={client.current} serviceOnly />
        : <LocalHomeSurface client={client.current} onOpenServices={openServices} />}
  </LocalDashboardShell>;
}
