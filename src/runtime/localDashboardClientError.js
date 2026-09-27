export class LocalDashboardClientError extends Error {
  constructor(kind = 'error') {
    super(kind === 'unavailable' ? 'Local dashboard service is unavailable.' : 'Local dashboard request failed.');
    this.name = 'LocalDashboardClientError';
    this.kind = kind;
  }
}

