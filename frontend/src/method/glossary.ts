// Shared English copy for issue #8. The method panel can import these definitions too.
// These explain terms; scientific values, variable definitions and caveats still come from JSON.
export const glossary = {
  trend: {
    label: 'Trend',
    definition: 'A long-term pattern of change, despite ups and downs from year to year. Its rate tells us how fast the values change.',
  },
  anomaly: {
    label: 'Anomaly',
    definition: 'How much a value differs from the average for a stated reference period. Always read it together with that reference period.',
  },
  p_value: {
    label: 'p-value',
    definition: 'Under the test’s assumptions, p is the chance of a result this extreme or more extreme if there were no trend. It is not the chance that the claim is false.',
  },
  confidence_interval: {
    label: 'Confidence interval',
    definition: 'A range showing uncertainty in the estimated rate of change, under the method’s assumptions. A wider range means a less precise estimate.',
  },
  reanalysis: {
    label: 'Reanalysis',
    definition: 'A weather model guided by observations to build a consistent record of past conditions. It is not a thermometer reading at the selected point.',
  },
  period_robustness: {
    label: 'Period robustness',
    definition: 'We repeat the trend check with slightly different start and end years. If the conclusion changes a lot, it depends too much on the chosen period.',
  },
  witness_station: {
    label: 'Witness station',
    definition: 'A nearby weather station provides a second record to compare with the main data source. It may have gaps or be unavailable, and the records can disagree.',
  },
} as const;

export type GlossaryTerm = keyof typeof glossary;

export const significanceCaution = 'Statistical significance does not tell us how large or important a change is.';
export const anomalyCaution = 'An anomaly uses a reference average; it does not mean an error or an unusual event.';
