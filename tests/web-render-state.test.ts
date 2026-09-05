import test from "node:test";
import assert from "node:assert/strict";
import { isRenderTransitionAllowed } from "../src/web/render-state";
import { SupabaseControlPlaneStore } from "../src/web/supabase-store";

test("render transitions only advance along the worker state machine", () => {
  assert.equal(isRenderTransitionAllowed("building_scene", "rendering"), true);
  assert.equal(isRenderTransitionAllowed("queued", "completed"), false);
  assert.equal(isRenderTransitionAllowed("completed", "failed"), false);
});

test("Supabase render transitions condition on the expected current status", async () => {
  const operations: Array<{ filters: Array<[string, unknown]>; value?: unknown }> = [];
  const client = {
    from: () => {
      const operation = { filters: [] as Array<[string, unknown]>, value: undefined as unknown };
      operations.push(operation);
      const query = {
        update: (value: unknown) => { operation.value = value; return query; },
        eq: (key: string, value: unknown) => { operation.filters.push([key, value]); return query; },
        select: () => query,
        maybeSingle: async () => ({ data: { id: "rj_1" }, error: null }),
      };
      return query;
    },
  } as never;

  const store = new SupabaseControlPlaneStore(client);
  assert.equal(await store.transitionRenderJob("rj_1", "building_scene", { status: "rendering", progress: 55 }), true);
  assert.deepEqual(operations[0].filters, [["id", "rj_1"], ["status", "building_scene"]]);
  assert.deepEqual(operations[0].value, { status: "rendering", progress: 55 });
});
