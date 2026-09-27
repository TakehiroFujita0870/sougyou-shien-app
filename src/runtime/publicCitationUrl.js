const SECRET_PARAMETER_NAMES = new Set([
  'access_token', 'api_key', 'apikey', 'auth', 'authorization', 'code', 'hdnea', 'hdnts',
  'jwt', 'key', 'private_key', 'password', 'rlkey', 'secret', 'session', 'signature', 'sig', 'token',
]);
const SECRET_PARAMETER_MARKERS = [
  'token', 'credential', 'signature', 'secret', 'password', 'passwd', 'authorization',
  'authkey', 'sessionid', 'keypairid',
];
const NORMALIZED_SECRET_PARAMETER_NAMES = new Set(
  [...SECRET_PARAMETER_NAMES].map((item) => item.replace(/[^a-z0-9]/g, '')),
);

function isSensitiveParameter(name) {
  const normalized = name.toLowerCase().replace(/[^a-z0-9]/g, '');
  return NORMALIZED_SECRET_PARAMETER_NAMES.has(normalized)
    || SECRET_PARAMETER_MARKERS.some((marker) => normalized.includes(marker));
}

function hasSensitiveParameter(parameters) {
  for (const [name] of parameters) {
    if (isSensitiveParameter(name)) return true;
  }
  return false;
}

/** Return a normalized public HTTP(S) citation URL, or null if unsafe. */
export function safePublicCitationUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null;
    if (hasSensitiveParameter(url.searchParams) || hasSensitiveParameter(new URLSearchParams(url.hash.slice(1)))) return null;
    return url.href;
  } catch {
    return null;
  }
}
