import { createRoot } from 'react-dom/client';
import { ErrorBoundary } from '../src/ErrorBoundary';

function BrokenCard(): never { throw new Error('Intentional rendering failure for recovery verification'); }
createRoot(document.getElementById('root')!).render(<ErrorBoundary><BrokenCard /></ErrorBoundary>);
