import { useId } from 'react';
import { methodIntro, methodSteps } from './text';
import './method.css';

// "How the detective decides": the method in plain words. Static text; it shows no numbers.
export function HowItDecides() {
  const id = useId();
  return <section className="method" aria-labelledby={id} data-testid="method">
    <h3 id={id}>How the detective decides</h3>
    <p className="method-intro">{methodIntro}</p>
    <dl>{methodSteps.map(step => <div key={step.id} data-method={step.id}>
      <dt>{step.title}</dt>
      <dd>{step.body}</dd>
    </div>)}</dl>
  </section>;
}
