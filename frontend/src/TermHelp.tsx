import { useId, useRef, useState } from 'react';
import { anomalyCaution, glossary, significanceCaution, type GlossaryTerm } from './method/glossary';
import './term-help.css';

// In-flow explanations work with touch and keyboard and do not cover a chart or get clipped by a table.
export function TermHelp({ term }: { term: GlossaryTerm }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const entry = glossary[term];
  return <span className="term-help" onKeyDown={event => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation(); setOpen(false); button.current?.focus();
    }
  }}>
    <button ref={button} type="button" className="term-help-button" aria-label={`Explain ${entry.label.toLowerCase()}`} aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>?</button>
    <span id={id} className="term-help-text" role="note" hidden={!open}>{entry.definition}</span>
  </span>;
}

export function WordGlossary() {
  return <details className="word-glossary">
    <summary>Words in this check <span>Plain-language definitions</span></summary>
    <div className="glossary-body">
      <dl>{Object.entries(glossary).map(([key, entry]) => <div key={key} data-term={key}>
        <dt>{entry.label}</dt><dd>{entry.definition}</dd>
      </div>)}</dl>
      <p>{anomalyCaution}</p>
      <p>{significanceCaution}</p>
    </div>
  </details>;
}
