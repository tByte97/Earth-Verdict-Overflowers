import { useId, useState } from 'react';
import type { CheckResult } from './types';
import { downloadCaseCsv } from './csv';
import { parseHash } from './url';
import './case-file.css';

// The case file: the result as CSV, and a link that reopens this view. The URL hash is
// already kept in sync by the app, so the link is simply the current address.
export function CaseFile({ result }: { result: CheckResult }) {
  const id = useId();
  const [copied, setCopied] = useState('');
  const linkable = parseHash(window.location.hash) !== null;
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied('Link copied.');
    } catch {
      setCopied(`Copy this link: ${window.location.href}`);
    }
  }
  return <section className="case-file" aria-labelledby={id} data-testid="case-file">
    <h3 id={id}>Case file</h3>
    <p>The series, trend line, station and test results exactly as the backend returned them.</p>
    <div className="case-file-actions">
      <button type="button" className="case-file-button" onClick={() => downloadCaseCsv(result)}>Download CSV</button>
      {linkable && <button type="button" className="case-file-button" onClick={copyLink}>Copy link to this case</button>}
    </div>
    <p className="case-file-status" role="status">{copied}</p>
  </section>;
}
