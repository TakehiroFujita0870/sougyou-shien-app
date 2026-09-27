import { expect, it } from 'vitest';
import { safePublicCitationUrl } from './publicCitationUrl';

it('keeps ordinary public query and fragment URLs', () => {
  expect(safePublicCitationUrl('https://example.test/report?id=1#section')).toBe('https://example.test/report?id=1#section');
});

it.each([
  'https://example.test/report?access_token=secret',
  'https://example.test/report?refresh_token=secret',
  'https://example.test/report?private_key=secret',
  'https://example.test/report?X-Amz-Signature=secret',
  'https://example.test/report?X-Amz-Credential=secret',
  'https://example.test/report?X-Amz-Security-Token=secret',
  'https://example.test/share?rlkey=secret',
  'https://example.test/report#access_token=secret',
  'https://user:pass@example.test/report',
  'javascript:alert(1)',
])('rejects unsafe citation URLs: %s', (url) => {
  expect(safePublicCitationUrl(url)).toBeNull();
});
