// Rounded results from docs/phase12-ppo-pilot-results.md, not live telemetry.
export const repositoryUrl = 'https://github.com/Ronak3000/hft-hybrid-bot';
// Frozen in-sample development result, identity-checked before rendering.
export const causalCandidate = {
  modelSha256: 'c3e487e563fb2fc314f3ca9ebd29e6ae38779398cc71221fe182e16090875e5c',
  reportSha256: '66acc2500af976123f8858f79ce0c4fa1c30cac968d1debfc44f0bb6479627ca',
  trainingCaptures: 10,
  fills: 95,
  grossPnl: '1.179215',
  fees: '6.52981764',
  netPnl: '-5.35060264',
} as const;
export const entryGuardStudy = {
  reportSha256: '28f2ef7c39ec8166591a8efe97c061b86be362883b2a4e9c39bdad5705361bc5',
  trainingCaptures: 10,
  unguardedFills: 95,
  unguardedNetPnl: '-5.35060264',
  guardedFills: 0,
  guardedNetPnl: '0',
} as const;
// Frozen collection-plan summary, not a live capture-progress counter.
export const nextStudy = {
  name: 'btcusdt-ppo-v2-activity-v1',
  trainingSessions: 10,
  validationSessions: 5,
  testSessions: 10,
  deltasPerSession: 10_000,
  planPath: 'data/studies/btcusdt-ppo-v2-activity-v1.json',
  firstSession: 'train-001',
} as const;
export const pilot = {
  date: '2026-09-11',
  sessions: 5,
  depthDeltas: 50_000,
  seeds: [7, 19, 43],
  trainingStepsPerSeed: 102_400,
  testSessions: 2,
  makerFee: '0.1%',
  orderLatency: '1 ms',
  quoteSize: '0.001 BTC',
  inventoryLimit: '0.01 BTC',
  reportSha256: '4d6b4c11bc5b9b98e9c3c85b94ecffff49dead2588403a15eff79f43fa11204b',
  source: `${repositoryUrl}/blob/main/docs/phase12-ppo-pilot-results.md`,
  policies: [
    { name: 'Inventory skew', pnl: -3.40, kind: 'Rule-based' },
    { name: 'Avellaneda–Stoikov', pnl: -34.47, kind: 'Rule-based' },
    { name: 'PPO · seed mean', pnl: -45.58, kind: 'Learned policy' },
    { name: 'Seeded random', pnl: -48.72, kind: 'Control' },
    { name: 'Fixed spread', pnl: -51.18, kind: 'Control' },
  ],
} as const;
