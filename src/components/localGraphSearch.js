export function searchGraphNodes(nodes, query) {
  const needle = query.trim().toLocaleLowerCase('ja');
  if (!needle) return { results: [], total: 0 };

  const results = [];
  let total = 0;
  for (const node of nodes) {
    if (!String(node.label ?? '').toLocaleLowerCase('ja').includes(needle)) continue;
    total += 1;
    if (results.length < 12) results.push(node);
  }
  return { results, total };
}
