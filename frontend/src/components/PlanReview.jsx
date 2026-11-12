// Plan review (Phase 6): the model proposed these steps and NO
// tool has run yet. Approving sends the original message with the
// plan attached; the server refuses to execute a plan that was
// never approved. Cancelling sends nothing at all.
export default function PlanReview({ plan, message, onApprove, onCancel }) {
  return (
    <div className="plan-review">
      <h3>Proposed plan</h3>
      <p className="muted">
        For: <em>{message}</em> — nothing has run yet. Approve to
        execute, or cancel to drop it.
      </p>
      <ol>
        {plan.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      <button type="button" onClick={onApprove}>
        Approve &amp; run
      </button>{' '}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  )
}
