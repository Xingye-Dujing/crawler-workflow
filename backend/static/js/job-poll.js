/* One poller for every background document/model job (`/api/jobs/<id>`).
 *
 * Report HTML, paper PDF, chart PDF and the AI connection test all run off the Flask
 * request thread. Their POST answers `{ok, job:{id,state}}`; this waits for the job's
 * `result`, which is the body the old synchronous route returned. A missing id, a lost
 * job or a timeout is an error, never a silent "saved" toast.
 */
async function awaitDocumentJob(jobId, timeoutMs) {
    var deadline = Date.now() + (timeoutMs || 1200000);
    if (!jobId) throw new Error(I18n.t('exportsMgr.reportFailed'));
    while (Date.now() < deadline) {
        var resp = await fetch('/api/jobs/' + encodeURIComponent(jobId));
        var answer = await resp.json();
        if (!answer.ok) throw new Error(answer.error || I18n.t('exportsMgr.reportFailed'));
        var job = answer.job || {};
        if (job.state === 'done') return job.result || { ok: false, error: I18n.t('exportsMgr.reportFailed') };
        if (job.state === 'failed') throw new Error(job.error || I18n.t('exportsMgr.reportFailed'));
        await new Promise(function (resolve) { setTimeout(resolve, 600); });
    }
    throw new Error(I18n.t('exportsMgr.jobTimeout'));
}
