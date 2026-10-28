'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

export function CopyCommand({ command }: { command: string }) {
  const [status, setStatus] = useState('');

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setStatus('Copied');
    } catch {
      setStatus('Select and copy the command manually');
    }
  }

  return (
    <div className="copy-command">
      <code>{command}</code>
      <button type="button" onClick={copy} aria-label="Copy capture command" className="copy-command-button">
        {status === 'Copied' ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
        Copy
      </button>
      <span role="status" className="copy-command-status">{status}</span>
    </div>
  );
}
