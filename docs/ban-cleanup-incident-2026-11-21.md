# Ban reaction and moderator cleanup investigation

This is the follow-up to PR #43, investigated on 26 November 2026. The original
report concerns 21 November; the prior fix merged/deployed on 24 November.

## Evidence and attribution

The intake history records PR #43, head `c8c72657833f14180caac37819555ceeea084639`,
merged as `a3f8bdec8e6d2ce41a2af11bf33459b3176279e5`, and Deploy Automator run
`45356243659`. That fix added user-token reads, item_user fallback and ID search.
It did not supply the incident's Slack event ID or a correlated CloudWatch trace.

Current local AWS access fails with `AWS Gate is closed or denied: HTTP 403
(Gate closed)`. Thus neither the exact failed November delivery nor the phone's
network condition can be established here. The router, Lambda and Slack API
failure modes below are reproduced defects, not a claimed historical trace.
Alexey's phone confirmation is still required for acceptance.

A read-only audit of the moderator's retained SQLite records found five
previously seen parents disappearing outside the poller on 21 November: three
placement misses (agency pitch, introduction, naked social link) had jev votes
of 0.61, 0.56 and 0.46, all below its review floor; two technical course questions
were keep votes of 0.98 and 0.95. The records identify neither the deleting actor
nor messages deleted before first collection. The detailed audit and regression
fixtures live in `DataTalksClub/slack-moderation`,
`docs/nov21-misses-and-thread-cleanup.md`. That patch adds narrow deterministic
placement rules, preserving technical discussion and the AI deletion threshold.

## Reproduced automation failures and fixes

- Router discarded every Slack HTTP-timeout retry, even if the first invocation
  never reached the automator. Ban retries are now forwarded. An asynchronous
  invoke must return 202 before acknowledgement; `AUTOMATOR_ACCEPTED` includes
  the Slack event ID for correlation. Non-admin reactions remain ignored.
- Automator marked an event seen before processing and retained it after errors,
  suppressing warm-container Lambda retries. Failed processing now releases the
  event ID; successful deliveries remain deduplicated within the warm container.
- Search errors returned partial/empty success. They now fail visibly, while
  cleanup still handles the reacted message and other available matches.
- Indexed search alone can omit recent messages. Cleanup supplements search with
  paginated public history and replies on recently active old roots, checking
  the offender ID and exact lookback cutoff. Reacted/indexed messages are handled
  before that longer inventory scan. Private channels remain search-visible only
  to the configured user token; no token can enumerate inaccessible channels.
- Thread enumeration and reply audit fetch stopped at page one. Both now follow
  cursors, reject incomplete pagination, and distinguish read failure from an
  empty thread. A failed child deletion retains its parent for retry. Individual
  failures do not prevent cleanup elsewhere; the moderator summary says
  `INCOMPLETE` and the handler raises for Lambda async retry.
- Ordinary DELETE_MESSAGE used no thread_ts at the audit boundary and left bot
  replies. It now supplies thread context and removes bot replies too. Every
  actual deletion retains the existing audit-before-delete guard.
- Partial retries may encounter already removed messages. A separate successful
  history/thread read must prove absence; failed audit or read access does not
  bypass the deletion guard.

The moderator previously tied child deletion to live author notices and their
message templates. Its companion patch makes cleanup independent of notices,
fetches the full thread, and durably queues children before parent removal.

## Validation and remaining live evidence

All reproductions use fixture events, mocked Slack/Lambda APIs and temporary
SQLite state. Only changed-path tests are run locally; full suites run in CI.
No real channel messages, users, moderation state or historical data are changed
by this investigation. CI deployment of code uses the normal repository flow.

Outstanding: inspect the incident's router/automator logs once AWS read access
is available, confirm deployment and scan duration against the Lambda timeout,
and obtain Alexey's phone verification. A sweep disappearance record is not
proof of a specific admin reaction or a client-side network miss.

Protocol references: Slack documents cursor pagination and thread retrieval in
[conversations.replies](https://docs.slack.dev/reference/methods/conversations.replies/)
and user-token `search:read` access in
[search.messages](https://docs.slack.dev/reference/methods/search.messages/).
