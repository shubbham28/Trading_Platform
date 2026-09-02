import { Router, Request, Response } from 'express';
import { proxyToPython } from '../utils/python';

const router = Router();

/**
 * Passthrough for the Python engine's own routes.
 *
 * Bots, the risk gate, the audit log and reconciliation all live in the engine.
 * Node forwards them unchanged rather than reshaping anything: a BFF that
 * rewrites a payload becomes a second place where the API's shape is defined,
 * and the two drift.
 *
 * The path is forwarded verbatim, so /api/bots/3/clone reaches /bots/3/clone.
 */
const passthrough = (prefix: string) => async (req: Request, res: Response) => {
  const suffix = req.path === '/' ? '' : req.path;
  await proxyToPython(req, res, `${prefix}${suffix}`);
};

router.use('/bots', passthrough('/bots'));
router.use('/audit', passthrough('/audit'));
router.use('/risk', passthrough('/risk'));
router.use('/reconciliation', passthrough('/reconciliation'));
// Live gating. Forwarded like everything else -- the approval queue is the most
// safety-critical path here, so it gets no special reshaping in Node.
router.use('/live', passthrough('/live'));
router.use('/approvals', passthrough('/approvals'));

export default router;
