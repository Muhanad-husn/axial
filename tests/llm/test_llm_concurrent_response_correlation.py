"""Diagnostic pin for issue #469 (`axial names merge` parse-failure rate
scales with `--workers`, 6 at 36 workers to 17 at 128, dominant error "merge
response placed none of the batch's surface forms").

Concurrency must not change what a model returns; #469's own investigation
asks whether it is instead a CLIENT-side artifact -- specifically, a race
under load where one concurrent call's parser ends up seeing a DIFFERENT
call's response body. `OpenRouterClient.complete()` shares one `httpx.Client`
across every worker (`axial.merge_names._decide_batch`'s own docstring: "the
client IS the connection pool"), so this test proves -- rather than assumes
-- that sharing never lets one call's response answer a different call.

Given   many threads share ONE `OpenRouterClient`, each sending a prompt that
        carries its own unique call id, against a transport that echoes that
        SAME id back with randomized latency (so responses complete out of
        submission order -- the exact interleaving a cross-thread mixup
        would need to manifest)
When    every call runs concurrently, well past #469's own reported worker
        counts (36-128)
Then    every `.complete()` call returns content bearing its OWN id, never
        another concurrent call's

This does not (and cannot, without a live corpus run) rule out a genuine
provider-side response/request mismatch under load, or a provider-side
quality change under concurrency -- both external to this codebase. What it
rules out is a client-side bug in `_post_with_deadline`/`complete()`
themselves: their `outcome`/`done` state is built fresh, as LOCAL variables,
inside every call (never a module- or instance-level shared buffer), so
there is no channel through which one call's response could reach another's
parser. This test is the executable version of that code-reading argument.
"""

from __future__ import annotations

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from axial.llm import OpenRouterClient

# Comfortably past #469's own reported sweep (36-128 workers) and the merge
# pass's own default (36) -- if a cross-wire hazard exists at all, it should
# show up well before this.
_CONCURRENT_CALLS = 200
_WORKERS = 64


def _echoing_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    prompt = body["messages"][0]["content"]
    call_id = re.search(r"CALL-(\d+)", prompt).group(1)
    # Randomized latency, independent per call, so responses land back on
    # their calling threads in an order that has nothing to do with
    # submission order -- the interleaving a cross-thread mixup would need.
    time.sleep(random.uniform(0, 0.02))
    return httpx.Response(200, json={"choices": [{"message": {"content": f"ECHO-{call_id}"}}]})


def test_concurrent_shared_client_calls_never_cross_wires_between_prompts():
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(_echoing_handler),
    )

    def _call(call_id: int) -> tuple[int, str]:
        return call_id, client.complete(f"CALL-{call_id} merge these names")

    mismatches: list[str] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
        futures = [executor.submit(_call, i) for i in range(_CONCURRENT_CALLS)]
        for future in as_completed(futures):
            call_id, content = future.result()
            if content != f"ECHO-{call_id}":
                mismatches.append(f"call {call_id} got back {content!r}")

    assert not mismatches, (
        f"{len(mismatches)}/{_CONCURRENT_CALLS} concurrent call(s) received a DIFFERENT "
        f"call's response -- client-side cross-wire contamination: {mismatches[:5]}"
    )
