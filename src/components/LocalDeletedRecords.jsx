import { useEffect, useRef, useState } from 'react';
import './LocalDeletedRecords.css';

const KIND_LABELS = { idea: 'アイデア', asset: 'アセット' };

function isValidRecord(record) {
  return record && ['idea', 'asset'].includes(record.kind)
    && typeof record.id === 'string' && record.id.trim().length > 0
    && typeof record.title === 'string' && typeof record.description === 'string'
    && Number.isSafeInteger(record.revision) && record.revision >= (record.kind === 'idea' ? 0 : 1);
}

/** Restores archived records through the local client without owning lifecycle controls. */
export function LocalDeletedRecords({ client }) {
  const [listing, setListing] = useState({ status: 'loading', records: [] });
  const [attempt, setAttempt] = useState(0);
  const [pendingKey, setPendingKey] = useState('');
  const [notice, setNotice] = useState('');
  const actionController = useRef(null);

  async function readRecords(signal, preserveRecords = false) {
    setListing((current) => ({ status: 'loading', records: preserveRecords ? current.records : [] }));
    try {
      const result = await client.getDeletedRecords({ signal });
      if (signal.aborted) return;
      if (result.status === 'stopped' || result.status === 'failed') {
        setListing({ status: result.status, records: [] });
        return result.status === 'stopped';
      }
      if (!['ready', 'empty'].includes(result.status) || !Array.isArray(result.records) || result.records.some((record) => !isValidRecord(record))) {
        throw new Error('Invalid deleted-record response');
      }
      setListing({ status: result.records.length ? 'ready' : 'empty', records: result.records });
      return true;
    } catch {
      if (!signal.aborted) setListing((current) => ({ status: 'failed', records: preserveRecords ? current.records : [] }));
      return false;
    }
  }

  useEffect(() => {
    actionController.current?.abort();
    actionController.current = null;
    setPendingKey('');
    setNotice('');
    const controller = new AbortController();
    void readRecords(controller.signal);
    return () => {
      controller.abort();
      actionController.current?.abort();
    };
  }, [client, attempt]);

  async function restore(record) {
    const key = JSON.stringify([record.kind, record.id]);
    if (pendingKey || !isValidRecord(record) || typeof client.restoreRecord !== 'function') return;
    const controller = new AbortController();
    actionController.current = controller;
    setPendingKey(key);
    setNotice('');
    try {
      await client.restoreRecord(record.kind, record.id, record.revision, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setNotice(`${record.title}を復元しました。`);
      const refreshed = await readRecords(controller.signal, true);
      if (!refreshed && !controller.signal.aborted) setNotice(`${record.title}を復元しました。削除済み一覧を更新できませんでした。再読み込みしてください。`);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error?.kind === 'conflict') {
        const refreshed = await readRecords(controller.signal, true);
        if (!controller.signal.aborted) setNotice(refreshed
          ? '他の更新があり復元できませんでした。最新の一覧を読み直しました。内容を確認してください。'
          : '他の更新があり復元できませんでした。最新の一覧を読み込めません。再読み込みしてください。');
      } else {
        setNotice('復元できませんでした。状態を確認して、もう一度お試しください。');
      }
    } finally {
      if (!controller.signal.aborted) {
        setPendingKey('');
        actionController.current = null;
      }
    }
  }

  const initialLoading = listing.status === 'loading' && listing.records.length === 0;
  return <section className="local-deleted-records" aria-labelledby="deleted-records-heading">
    <header className="local-deleted-records__heading">
      <div>
        <h2 id="deleted-records-heading">削除済みの記録</h2>
        <p>ここからアイデアやアセットを復元できます。</p>
      </div>
      {listing.status === 'loading' && !initialLoading && <span role="status">一覧を更新中…</span>}
    </header>

    {initialLoading && <p role="status" className="local-deleted-records__message">削除済みの記録を読み込んでいます。</p>}
    {listing.status === 'empty' && <p className="local-deleted-records__message">削除済みの記録はありません。</p>}
    {listing.status === 'stopped' && <p role="status" className="local-deleted-records__message">Dots.が停止中です。復元するにはサービスを起動してください。</p>}
    {listing.status === 'failed' && <div className="local-deleted-records__message" role="alert">
      <span>削除済みの記録を読み込めませんでした。</span>
      <button type="button" disabled={Boolean(pendingKey)} onClick={() => setAttempt((value) => value + 1)}>再読み込み</button>
    </div>}

    {listing.records.length > 0 && <ul className="local-deleted-records__list" aria-label="削除済みのアイデアとアセット">
      {listing.records.map((record) => {
        const key = JSON.stringify([record.kind, record.id]);
        return <li key={key} className="local-deleted-records__item">
          <div className="local-deleted-records__copy">
            <div className="local-deleted-records__title-row"><h3>{record.title}</h3><span>{KIND_LABELS[record.kind]}</span></div>
            {record.description && <p>{record.description}</p>}
          </div>
          <button type="button" aria-label={`「${record.title}」を復元`} disabled={Boolean(pendingKey) || listing.status !== 'ready' || !isValidRecord(record)} onClick={() => { void restore(record); }}>
            {pendingKey === key ? '復元中…' : '復元'}
          </button>
        </li>;
      })}
    </ul>}
    {notice && <p role="status" aria-live="polite" className="local-deleted-records__notice">{notice}</p>}
  </section>;
}

export default LocalDeletedRecords;
