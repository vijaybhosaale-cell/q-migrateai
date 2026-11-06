// AI models: compare the five risk models on the same held-out data.
import { api, post } from "../api.js";
import { heatmap, hbars, lineChart, whiskers } from "../charts.js";
import { can } from "../state.js";
import { $, emptyState, esc, toast } from "../ui.js";
const f3 = (v) => (v == null ? "–" : v.toFixed(3));
export async function modelsPage(el) {
    let m;
    try {
        m = await api("/models");
    }
    catch (e) {
        el.innerHTML = emptyState("No models trained yet", esc(e.message), `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
        return;
    }
    draw(el, m);
}
function draw(el, m) {
    const primary = m.models.find((x) => x.key === m.primary);
    const best = [...m.models].sort((a, b) => b.cv_macro_f1_mean - a.cv_macro_f1_mean)[0];
    const curve = m.curve;
    el.innerHTML = `
  <section class="panel panel-pad">
    <div class="flex flex-wrap items-start gap-4">
      <div class="max-w-3xl">
        <h2>Which model should decide the risk class?</h2>
        <p class="mt-1 text-[14px] text-fog">Five models learn the same task: predict the risk class an analyst would give each asset.
          They train on ${m.split.train} assets and are scored on ${m.split.test} assets they never saw, then checked again with 5-fold cross-validation.
          The platform uses <span class="text-mist">${esc(primary.name)}</span>; ${best.key === m.primary ? "it also has the best cross-validated score here." : `on this estate <span class="text-mist">${esc(best.name)}</span> scores higher, which is worth reviewing.`}</p>
        <p class="mt-2 text-[12.5px] text-risk-medium">The labels come from the simulator, which imitates an analyst's past decisions with a hidden rule. These scores show the models can learn that rule; they are not proof of accuracy on a real company.</p>
      </div>
      ${can("discover") ? `<div class="ml-auto flex items-end gap-2"><div><label class="label" for="m-seed">Random seed</label>
        <input id="m-seed" type="number" class="input w-24" value="${m.seed}" min="1" max="99999"></div>
        <button class="btn" data-retrain>Retrain</button></div>` : ""}
    </div>
  </section>

  <div class="mt-5 grid gap-5 xl:grid-cols-2">
    <section class="panel panel-pad">
      <h2>Cross-validated macro-F1</h2>
      <p class="muted text-[13px] mb-4">Mean of 5 folds, with the spread of ±1 standard deviation. Macro-F1 weighs every class equally, so a model cannot score well by ignoring Critical.</p>
      ${whiskers(m.models.map((x) => ({ label: x.name, mean: x.cv_macro_f1_mean, std: x.cv_macro_f1_std, highlight: x.key === m.primary })))}
    </section>
    <section class="panel panel-pad">
      <div class="flex flex-wrap items-center gap-3"><h2>Confusion matrix</h2>
        <select class="input w-auto ml-auto" data-cm aria-label="Model">${m.models.map((x) => `<option value="${x.key}" ${x.key === m.primary ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>
      <p class="muted text-[13px] mb-3">Rows are the analyst's class, columns the model's prediction, on the ${m.split.test} held-out assets. Violet is correct, red is a mistake.</p>
      <div data-cm-body></div>
    </section>
  </div>

  <section class="panel mt-5">
    <div class="px-5 pt-5"><h2>Held-out test results</h2></div>
    <div class="overflow-x-auto mt-2"><table class="tbl">
      <thead><tr><th>Model</th><th>Family</th><th>Inputs</th><th class="text-right">Accuracy</th><th class="text-right">Macro-F1</th>
        <th class="text-right">Critical recall</th><th class="text-right">High + Critical recall</th><th class="text-right">CV macro-F1</th></tr></thead>
      <tbody>${m.models.map((x) => `<tr class="${x.key === m.primary ? "bg-lattice-soft/30" : ""}">
        <td class="${x.key === m.primary ? "text-mist font-medium" : ""}">${esc(x.name)}${x.key === m.primary ? ` <span class="chip ml-1 border-lattice/60 text-lattice">In use</span>` : ""}</td>
        <td class="text-fog">${esc(x.family)}</td><td class="text-fog text-[12.5px]">${esc(x.inputs)}</td>
        <td class="text-right tabular">${f3(x.accuracy)}</td><td class="text-right tabular">${f3(x.macro_f1)}</td>
        <td class="text-right tabular">${f3(x.critical_recall)}</td><td class="text-right tabular">${f3(x.high_critical_recall)}</td>
        <td class="text-right tabular whitespace-nowrap">${f3(x.cv_macro_f1_mean)} <span class="text-fog">± ${f3(x.cv_macro_f1_std)}</span></td></tr>`).join("")}</tbody>
    </table></div>
    <p class="p-5 pt-3 text-[12.5px] text-fog">Critical recall is the share of truly Critical assets the model catches. For a security team a missed Critical asset costs more than a false alarm.</p>
  </section>

  <div class="mt-5 grid gap-5 xl:grid-cols-2">
    <section class="panel panel-pad">
      <h2>What the neural network relies on</h2>
      <p class="muted text-[13px] mb-4">Permutation importance: how much macro-F1 drops when one feature is shuffled. Features from the dependency graph are marked.</p>
      ${hbars(m.importance.neural_network.slice(0, 12).map((f) => ({
        label: f.label, value: Math.max(0, f.importance), display: f.importance.toFixed(3),
        color: GRAPH_FEATURES.has(f.feature) ? "#9B8CFF" : "#8B96B3", title: `${f.label}: ± ${f.std}`
    })), undefined, "minmax(150px,260px)")}
      <p class="mt-3 text-[12.5px] text-fog"><span class="inline-block h-2 w-2 rounded-full bg-lattice mr-1"></span>graph feature
        <span class="inline-block h-2 w-2 rounded-full bg-fog ml-3 mr-1"></span>asset feature</p>
    </section>
    <section class="panel panel-pad">
      <h2>Training curve</h2>
      <p class="muted text-[13px] mb-2">${m.architecture.inputs} inputs, hidden layers ${m.architecture.hidden.join(" and ")}, ${m.architecture.outputs} classes, ${m.architecture.activation}, ${m.architecture.optimizer}, ${m.architecture.epochs} epochs.</p>
      ${lineChart([
        { name: "Train accuracy", color: "#8B96B3", points: curve.epoch.map((e, i) => [e, curve.train_accuracy[i]]) },
        { name: "Test accuracy", color: "#9B8CFF", points: curve.epoch.map((e, i) => [e, curve.test_accuracy[i]]) },
        { name: "Loss", color: "#F58A34", dashed: true, points: curve.epoch.map((e, i) => [e, Math.min(1, curve.loss[i])]) },
    ], { yMin: 0, yMax: 1, xLabel: "Epoch", yLabel: "Accuracy / loss", height: 250 })}
    </section>
  </div>`;
    const cmBody = $("[data-cm-body]", el);
    const showCm = (key) => {
        const x = m.models.find((y) => y.key === key);
        cmBody.innerHTML = heatmap(x.confusion, m.classes);
    };
    const select = $("[data-cm]", el);
    select.addEventListener("change", () => showCm(select.value));
    showCm(m.primary);
    $("[data-retrain]", el)?.addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        const seed = Number(($("#m-seed", el)).value) || 42;
        btn.disabled = true;
        btn.textContent = "Training…";
        try {
            const fresh = await post("/models/retrain", { seed });
            toast(`Models retrained with seed ${seed}.`, "ok");
            draw(el, fresh);
        }
        catch (err) {
            toast(err.message, "error");
            btn.disabled = false;
            btn.textContent = "Retrain";
        }
    });
}
const GRAPH_FEATURES = new Set(["dependency_impact", "pagerank", "betweenness", "in_degree", "out_degree",
    "inherited_exposure", "succ_qv_frac", "neighbor_mean_exposure"]);
