# The Delegation Blind Spot: Auditing Product Decisions from Agent Choices

# **The Delegation Blind Spot**

Auditing Product Decisions from Agent Choices

Shivam Gupta Independent Research

shivam1720406@gmail.com

20 September 2026

## **Abstract**

Successful agent execution need not identify which future product improvement its user would value. We present a decision-specific audit that maps a declared observation channel and product-value contrast to compatible intervals and witness populations. Its foundations are established identification and decision theory; the contribution is an executable measurement workflow and a controlled study of its limits. A frozen experiment makes 4,800 requests to two pinned model snapshots on shared synthetic tasks. All 36 conservative primary intervals remain unresolved despite different execution accuracy. An exploratory 2,400-call follow-up records supplied preferences and resolves three of nine comparisons per model. A deterministic extractor resolves seven of nine without model calls or calibration observations, exposing unnecessary uncertainty introduced by model-generated reports. A further 14,400 controlled multinomial simulations distinguish structural ambiguity from weak identification and finite calibration precision. We propose a sourcelabeled decision receipt and provide an offline viewer for inspecting the audit. These results motivate preserving decision-relevant structured input and diagnosing why a decision is unresolved before collecting more telemetry. The study contains no human participants or real customer outcomes. Full proofs, raw model provenance, controlled experiments, and reproducible analyses accompany the report.

## **1 Introduction**

Two customers ask their agents to book the same hotel. One values quiet; the other values proximity to a meeting. At current prices, the same hotel is best for both. Both agents execute perfectly, and the platform records indistinguishable transactions. The platform’s next question is different: should it invest in soundproofing or transport links? Successful bookings need not distinguish the populations that would favor those investments.

This ambiguity is possible with human choices as well. We do not claim that delegation creates nonidentification, or that more capable agents necessarily remove informa-

tion. Instead, we study a precise operational question: _does a specified stream of delegated activity support a specified future product decision?_ This requires distinguishing execution utility, information available to the company, and the customer’s value from a future change.

Our contribution is a reproducible decision-oriented audit. It reports bounds and competing compatible populations, then separates reasons the evidence may remain inconclusive. Structural ambiguity can require a different observation; sampling uncertainty can require better calibration or more data. These interventions are not interchangeable. The computational evaluation combines actual model responses, a deterministic extraction baseline, and controlled channels with analytically known identification properties.

The audit operationalizes existing identification principles for a declared future product contrast. Its mathematical results and linear programs have direct antecedents. The study evaluates this workflow on constructed preferences and utilities; it does not establish market prevalence, customer adoption, or commercial value.

## **2 Related work**

Blackwell’s comparison of experiments connects observations to decision value [2]. Linear partial monitoring makes the relation between payoff contrasts and observation spans explicit [6]. Optimal recovery relates inverse estimation to distances and moduli of continuity [4]. These supply the conceptual basis for our observability and lower-bound results.

The channel equation used here is closely related to label-shift estimation: a calibrated confusion matrix maps latent class prevalence to observable predictions [11]. Full prevalence recovery can require invertibility, whereas a particular contrast may remain identifiable without full recovery. Partial identification under measurement error provides linear-programming bounds and confidence-set propagation [5]. We use these established principles and expose their assumptions to product decisions.

Delegated choice itself has been studied through rationalization and menu interpretation [7], consumer pref-

erence transmission [8], and controlled tests of agent responses to product attributes and stated profiles [3]. Revealed-preference analysis can identify aspects of human-agent alignment from choices across menus under a mixture-of-Luce model [12]. That target and its menu variation differ from our calibrated population contrast and coarse logs. Unresolved intervals here do not refute identification from richer observations. Synthetic profiles are not equivalent to the human evidence in preferencetransmission studies. Prediction-powered inference and active sampling address efficient acquisition of true outcome labels [1, 10, 13]; our initial audit pilot uses those methods as antecedents and controls.

# **3 A decision-specific observation model**

Let _p ∈_ ∆ _K_ = _{p ∈_ R<sup>_K_</sup> : _p ≥_ 0 _,_ **1**<sup>_T_</sup> _p_ = 1 _}_ denote a population’s proportions across a declared finite intent taxonomy. A fixed agent, interface, and task distribution induce an _m × K_ column-stochastic channel _A_ , with

[Formula on PDF page 2 (6)](../assets/figure/formula-p0002-005.jpg)

Here _Y_ is a logged action category. Its definition is part of the measurement design. Logging a selected product type, logging type together with context, and logging the entire continuous menu are different experiments.

For product variants 1 and 0, let _dk_ be their independently specified difference in customer outcome for class _k_ . The target is

[Formula on PDF page 2 (9)](../assets/figure/formula-p0002-008.jpg)

This is a value contrast, not automatically a causal effect or financial return. Its causal interpretation requires an appropriate outcome design; an investment decision additionally requires costs and constraints. In the computational study, _d_ is a known mean over an independent finite bank of synthetic menus. We analyze uncertainty in estimated _d_ separately.

The compatible population set is _Pq_ = _{p ∈_ ∆ _K_ : _Ap_ = _q}_ . Define _L_ ( _q_ ) = min _p∈Pq d_<sup>_T_</sup> _p_ and _U_ ( _q_ ) = max _p∈Pq d_<sup>_T_</sup> _p_ . Compactness guarantees attainment. A positive lower endpoint supports variant 1 throughout the supplied model; a negative upper endpoint supports variant 0. A straddling interval supplies witness populations favoring opposite decisions. An interval touching zero may represent a tie, not a strict reversal.

# **4 Identification, ambiguity, and decision loss**

**Theorem 1** (Global and local identification) **.** _For known A, the contrast is identified for every feasible q if and only if d ∈_ row( _A_ ) _. At a fixed q, identification holds if and only if d is orthogonal to_ span( _Pq −Pq_ ) _._

_Proof sketch._ If _d_ = _A_<sup>_T_</sup> _v_ , then _d_<sup>_T_</sup> _p_ = _v_<sup>_T_</sup> _q_ . Otherwise a null vector _h_ with _Ah_ = 0 and _d_<sup>_T_</sup> _h̸_ = 0 exists. Column normalization gives **1**<sup>_T_</sup> _h_ = 0; perturbing an interior population in directions _±h_ constructs indistinguishable populations. The local statement follows from constancy over feasible differences.

The quantifiers matter. A rank-deficient channel can identify all contrasts at a boundary observation that isolates one class. Conversely, reconstructing all class proportions is stronger than learning one particular product contrast.

**Theorem 2** (Worst compatible contrast width) **.** _Let W_ ( _A, d_ ) = max _p,r∈_ ∆ _K_ : _Ap_ = _Ar |d_<sup>_T_</sup> ( _p − r_ ) _|. Then_

[Formula on PDF page 2 (17)](../assets/figure/formula-p0002-016.jpg)

[Formula on PDF page 2 (18)](../assets/figure/formula-p0002-017.jpg)

Every feasible difference has zero total mass and _ℓ_ 1 norm at most two. Conversely, its positive and negative parts can be completed with a common population mass. Linear-programming duality gives the distance expression. This is a standard inverse-problem quantity specialized to a decision contrast, not a new duality principle. _W_ is global: the interval at an actual _q_ can be narrower.

For action _b ∈{_ 0 _,_ 1 _}_ , value regret is _ℓ_ ( _b,_ ∆) = max(0 _,_ ∆) _− b_ ∆.

**Theorem 3** (Irreducible decision loss) **.** _Fix an exactly known q with attainable interval_ [ _L, U_ ] _. Every estimator based only on any number of iid draws from q has worst compatible mean absolute error at least_ ( _U − L_ ) _/_ 2 _and mean squared error at least_ ( _U − L_ )<sup>2</sup> _/_ 4 _. If L <_ 0 _< U , the exact-observation minimax randomized value regret is_

[Formula on PDF page 2 (22)](../assets/figure/formula-p0002-021.jpg)

_where t_<sup>_∗_</sup> _is the probability of choosing variant 1. Outside the straddling case, minimum regret is zero._

Endpoint populations generate the same observation law. Estimation lower bounds follow from triangle and squared-loss identities; balancing endpoint regrets ( _−L_ ) _t_ and _U_ (1 _− t_ ) proves the decision result. Randomization is a theoretical decision rule, not a recommendation to randomize a costly business commitment. Deterministic minimax regret is min( _−L, U_ ) in the straddling case.

The following results are stated in our notation for auditability. Full proofs and further extensions appear in Appendix A.

**Example.** With identical columns _A·_ 1 = _A·_ 2 = (0 _._ 8 _,_ 0 _._ 2)<sup>_T_</sup> and _d_ = ( _−_ 0 _._ 3 _,_ 0 _._ 5)<sup>_T_</sup> , all populations have the same action law. The interval is [ _−_ 0 _._ 3 _,_ 0 _._ 5] and _R_<sup>_∗_</sup> = 0 _._ 1875. More samples from this channel cannot resolve it. Direct outcome feedback or a new informative channel can.

# **5 Uncertainty and measurement design**

## **5.1 Attainable bounds with uncertain channels**

Suppose 0 _≤_ _<u>A</u> ≤ A ≤_ 1, every channel-column box intersects the probability simplex, and field frequencies lie in [ _<u>q, q</u>_ <u>].</u> Introduce joint masses _Jak_ = _Aakpk_ and impose

[Formula on PDF page 3 (7)](../assets/figure/formula-p0003-006.jpg)

[Formula on PDF page 3 (8)](../assets/figure/formula-p0003-007.jpg)

[Formula on PDF page 3 (9)](../assets/figure/formula-p0003-008.jpg)

Minimize and maximize _d_<sup>_T_</sup> _p_ over this linear feasible set. The reparameterization is exact for the declared rectangular model: divide each positive-mass column of _J_ by _pk_ to recover its channel; choose any feasible channel column when _pk_ = 0. Every original model maps back to such a joint mass. Sharpness is relative to this uncertainty description, not to unspecified correlated constraints.

The implementation verifies solver witnesses against the constraints and returns failure for infeasibility. Empty feasible sets must not become confident recommendations. If the channel and field sets cover with error probabilities _αA_ and _αq_ , the target interval covers with probability at least 1 _− αA − αq_ , conditional on model correctness. Independence of these coverage events is unnecessary for the union bound. We use simultaneous coordinate Clopper–Pearson boxes within each channel/field calculation. Their iid sampling assumptions must match the experiment.

If _d ∈_ [ _<u>d,</u> d_ ], optimize _<u>dT p</u>_ for the lower endpoint and _d_ _~~T~~ p_ for the upper endpoint. Nonnegativity of _p_ makes this exact for a rectangular outcome set. Its failure probability adds to the preceding bound. Unknown classes and channel drift are not automatically covered by these sampling intervals. Separately constructed coordinate boxes for coarse and fine logs need not be nested. Thus finite-sample interval widths across schemas are not ordered by the exact-channel coarsening theorem.

## **5.2 A bias-aware linear certificate**

For a known reference channel, select action weights _v_ before observing the field sample. Write _ϵ_ = �� _d − AT v_ �� _∞_ and _s_ = max _a va −_ min _a va_ . For _n_ iid observations from a deployed channel whose class columns are within total variation _τ_ of the reference,

[Formula on PDF page 3 (15)](../assets/figure/formula-p0003-014.jpg)

with probability at least 1 _− α_ . The terms separate approximation, channel drift, and sampling error. Our code minimizes this bound by linear programming independently of field observations. Estimated calibration must be covered by _τ_ or another uncertainty argument; substituting a point-estimated channel is not a coverage guarantee.

## **5.3 Record the measurement condition**

Suppose a probe _e_ is independently assigned with probability _ρe >_ 0, logged, and preserves population composition. Its joint channel is _B_ = vstack( _ρeAe_ ). It identifies _d_ exactly when _d_ belongs to the joint row span. Discarding the probe label replaces this with<sup>�</sup> _e_<sup>_ρeAe_andcan</sup> destroy information. For example, equally likely identity and row-swapped identity channels are fully informative when the probe is recorded but completely pooled when it is omitted. This is an implication of coarsening and classical experiment comparison, not evidence that any particular agent update is a coarsening.

# **6 Computational experiment**

## **6.1 Frozen design and provenance**

The main design was committed and pushed before its API calls. It is an exploratory, prospectively frozen computational study, not an externally preregistered human experiment. A separate one-call connectivity test is excluded. The main run queries GPT-5.4 Mini and GPT5.4 Nano, both pinned to their 17 March 2026 snapshots, on identical task records, interleaving model requests to reduce timing confounds. Prompts, exact requests, response identifiers, returned model versions, token usage, errors, and source hashes are retained. There are no tools or adaptive prompt changes during the run.

Three domain framings (travel, cloud plans, workflow software) share a mathematical generator. Each task has four alternatives with independently perturbed attributes, one of three context regimes, and randomized option order. Four declared intent classes use explicit numerical weights and a noncompensatory minimumattribute penalty. Models choose an option ID under a strict output schema. These are synthetic utility objec-

tives, not elicited human preferences; domain framings are not independent real-world datasets.

For each model and domain, calibration samples 80 tasks per intent class. Three independently sampled field cohorts (160 tasks each) have specified class mixtures: positive ( _._ 65 _, ._ 10 _, ._ 15 _, ._ 10), negative ( _._ 15 _, ._ 10 _, ._ 65 _, ._ 10), and near ( _._ 42 _, ._ 18 _, ._ 27 _, ._ 13). Thus each model is assigned 2,400 requests, totaling 4,800. Successful responses and transport failures are reported separately. Separate random streams generate calibration, field cohorts, futureoutcome banks, and outcome samples. The target contrasts compare best attainable utility after capacity versus flexibility investment, each with an identical affordability tradeoff, over 4,096 independent synthetic menus per domain. This assumes optimal future selection; it is not measured utility of the tested model under those future variants.

# **6.2 Targets, schemas, and baselines**

The primary target uses exact mean class contrasts from that finite outcome bank. It isolates observation-channel measurement from outcome estimation. A secondary analysis uses 2,048 samples from the bank and boundedoutcome uncertainty. Neither establishes real customer value.

We compare two declared logs: selected semantic product type (plus failure), and type paired with the three context regimes (plus failure). Both omit full continuous menu information. Unresolved intervals under these schemas are not proof of nonidentification from every possible observable feature.

Baselines include constrained least-squares prevalence estimation inspired by label-shift correction, a percentile bootstrap conditional on the estimated channel, and the joint-mass uncertainty diagnostic. The fixed-channel bootstrap omits calibration uncertainty and has no claimed finite-sample coverage. Exact-optimum, uniformrandom, and fixed-default choosers are algorithmic controls, not additional models or participants. We measure task success, synthetic utility regret, interval width, decision resolution, compatibility with the known synthetic target, and provider failures.

Primary intervals allocate _αA_ = _αq_ = _._ 02, giving at least 96% marginal coverage per contrast under the stated assumptions. Secondary outcome uncertainty adds _._ 01, giving 95%. These are not simultaneous guarantees across the model/domain/cohort/schema comparisons. We report all conditions and do not treat their observed coverage fraction as an independent repeated-sampling validation of the theorem.

# **6.3 Exploratory explicit-preference receipts**

After observing that all primary intervals were unresolved, we froze a separate follow-up before its new API calls. It asks the agent to report the largest of the four preference weights already present in its input. Selection uses the first 40 lexicographic calibration task IDs per domain/class and the first 80 field IDs per domain/cohort, without consulting their response correctness or utility. This yields 1,200 new requests per model. The original actions for exactly those task IDs provide an equal-count baseline. The primary follow-up comparison is attributeonly reporting against action-only logging, with nine domain/cohort conditions per model.

The receipt removes the offer menu. Its 1,200 calls per model repeat only 12 distinct prompts: four supplied weight profiles in three framings. Each profile has a unique leading attribute, so an accurate receipt directly reveals its synthetic class. It tests whether this explicit report produces a useful observation channel in the constructed problem. It does not test inference of private preferences or independently validate the supplied weights. A deterministic parser could recover these weights directly; a language model is not necessary for that operation in a deployed system. Matched observation counts do not equalize tokens, monetary cost, privacy exposure, or human elicitation burden.

The snapshots are unchanged. Receipt requests explicitly set reasoning effort to none; the primary requests use the documented default of none. The prompt and task change, rather than isolating a passive logging intervention. Repeated calls require a stable, independent response mechanism for the categorical sampling model. Moreover, the follow-up was chosen after the primary results and reuses original field draws and actions. Its fixed-design marginal interval statements are not selective guarantees conditional on that choice. Resolution counts are exploratory descriptions, not a confirmatory significance test.

# **6.4 AI-assisted research development and verification**

OpenAI Codex was used in an iterative author-directed workflow for problem formulation, literature retrieval, proof drafts, experiment protocols, code, analysis, visualizations, and manuscript text. Internal AI critiques informed revisions; they are not external peer review. Verification includes primary-source comparison, mathematical counterexamples, numerical constraint checks, automated tests, recorded API provenance, and exact reanalysis. These automated and source-based checks do not certify human-author review. The author is responsible for scrutinizing the work and its claims before submission. Research assistance is distinct from the two

[Table on PDF page 5 (3)](../assets/table/table-p0005-002.csv)

| Field metric | Mini | Nano | Paired measure, per model | Actions | Receipts |
| --- | --- | --- | --- | --- | --- |
| Tasks | 1,440 | 1,440 | Calibration per class/domain | 40 | 40 |
| Utility-maximizing choice | 73.19% | 55.69% | Field per cohort/domain | 80 | 80 |
| Mean synthetic regret | 0.0186 | 0.0573 | Resolved contrasts / conditions | 0 / 9 | 3 / 9 |
| Field delivery failures | 0.35% | 0.28% | Incorrect resolved contrasts | 0 | 0 |
|  |  |  | Mean interval width | 0.0872 | 0.0436 |

Table 1: Real model responses to constructed utility objectives. Regret is best available utility minus delivered utility, on the declared [0 _,_ 1] scale.

pinned models evaluated in the experiments.

Table 2: Exploratory comparison. Both models have the same reported interval summaries. Perfectly reporting the supplied leading attribute directly reveals the constructed intent class. Counts do not equalize monetary cost or elicitation burden.

# **7 Results**

## **7.1 Execution competence and decision uncertainty**

The primary run recorded 4,800 attempts, 4,783 valid choices, and 17 transport failures. Both returned model identifiers match their pinned requested snapshots. Failed records are retained as an observable category. No retries replace them.

Table 1 reports field-task performance, counting a failure as no delivered utility. Mini chooses a utility maximizer more often and incurs lower mean synthetic regret. These are descriptive results for the frozen generator, not a general model ranking. Calibration tasks are excluded from these field-performance denominators.

The joint-mass diagnostic leaves all 18 conditions per model unresolved. It contains each known synthetic target, but this does not establish an empirical coverage rate: conditions share calibration data, and the set is small and selected. Zero wrong certified decisions is achieved here by abstaining on every condition. Even the optimal-choice control leaves all 18 corresponding intervals unresolved. At this budget, conservative coordinate boxes are not a practically sufficient product-selection procedure.

The constrained point baseline selects the wrong sign in 2 of 18 Mini conditions and 4 of 18 Nano conditions. The fixed-channel percentile bootstrap contains the known target in 14 of 18 and 16 of 18 conditions, respectively. These are descriptive counts, not a calibrated coverage comparison. The bootstrap omits calibration error; the conservative method includes it but sacrifices decisiveness. This experiment does not isolate intrinsic channel nonidentification from finite-sample uncertainty.

## **7.2 Compute and interpretation**

Recorded tokens imply an estimated US$1.113 for the primary run at the documented standard rates. This is not an invoice: failed transport requests may have unreported billable usage. Timeouts and connection

resets are not evidence of model reasoning errors. Their temporal clustering also cautions against treating every operational error as an independent stationary draw. Conditional mathematical coverage statements must not be mistaken for verified provider independence.

The secondary analysis also propagates synthetic outcome estimation error and is more conservative. Exact outcome-bank values describe best attainable utility after future investment, not realized future behavior of the tested models. The primary findings justify investigating additional measurement channels, not declaring that all delegated product activity is inherently uninformative.

## **7.3 Explicit preference information at matched counts**

The exploratory follow-up recorded 2,400 completed receipt requests, with no delivery failures. Both models returned their requested snapshots and correctly reported the largest supplied weight on every calibration and field request. This is accuracy on 12 repeated, explicitly specified prompts, not evidence of general preference understanding. The two models therefore induce identical empirical receipt channels and identical receipt intervals on the shared task subset.

Each model’s receipt channel resolves three of nine primary follow-up conditions, compared with zero of nine using the matched original actions. All three resolved conditions are the positive cohort, one per domain; none contradicts the known synthetic target. The negative and near cohorts remain unresolved. Mean interval width decreases from 0.0872 for action logs to 0.0436 for receipts, a 50.0% reduction. These figures summarize the selected conditions and do not constitute a significance test or a post-selection coverage guarantee.

The result separates two limitations. Even a directly observed class does not resolve every small contrast under this finite-sample procedure. Yet the same number of observations is more useful when it records a relevant class attribute instead of a behavioral proxy. The receipt’s remaining uncertainty is sampling and channelcalibration uncertainty within the declared model, rather

## **Task competence on varied delegated-choice menus**

[Figure on PDF page 6 (4)](../assets/figure/figure-p0006-003.jpg)

Figure 1: Primary field-task performance by semantic framing. The three framings share a mathematical generator. Real provider failures remain in the operational scores.

than a demonstrated loss of the supplied class information. Since a deterministic extractor would provide the same field, this experiment supports explicit measurement design, not the necessity of an LLM receipt generator.

Reported usage implies an additional US$0.372 for the follow-up. Across the two studies, there are 7,200 attempted API requests, 7,183 valid responses, and 17 retained transport failures. The excluded connectivity test is not part of these counts. All preferences and product outcomes remain synthetic.

# **7.4 A deterministic baseline for supplied preferences**

The receipt experiment asks models to recover information already in a structured input. A new offline control parses those supplied weights directly and checks membership in the declared four-profile taxonomy. It uses the same 720 field records across the nine conditions, without their private intent labels. The known identity channel eliminates report-calibration uncertainty. With _αq_ = _._ 04, field-frequency bounds resolve seven of nine comparisons, with zero incorrect resolutions and mean width 0.02285. There are no calibration observations or new API calls. A direct Hoeffding interval for the bounded variable _dZ_ , using the same _._ 04 error budget, also resolves seven; its mean width is 0.02727. The methods are reported separately, not intersected.

This baseline changes the engineering interpretation of the receipt result. Given these structured inputs, routing the supplied attribute through an LLM and estimating its error channel is unnecessary. Preserving the field

is simpler and produces more decisive intervals in this selected benchmark. It still does not validate the supplied profile against a real customer. These reanalyses use the previously selected field draws and remain exploratory.

# **7.5 Structural ambiguity versus finite precision**

A separate controlled simulation isolates limitations conflated by the primary model experiment. Let

[Formula on PDF page 6 (14)](../assets/figure/formula-p0006-013.jpg)

The channel eigenvalues are 1 _, η, η, η_ . At _η_ = 0, every population has the same action law and the compatible contrast interval is [ _−._ 04 _, ._ 06]. For every _η >_ 0, _Aη_ is invertible and the exact-observation interval has zero width. Identification alone therefore does not describe the difficulty of the finite-sample inverse problem.

For known _Aη_ and _η >_ 0, write _d_<sup>¯</sup> = **1**<sup>_T_</sup> _d/_ 4. The weights _v_ = _d_<sup>¯</sup> **1** + ( _d − d_<sup>¯</sup> **1** ) _/η_ satisfy _A_<sup>_T_</sup> _η_<sup>_v_=</sup><sup>_d_,withrange</sup> range( _d_ ) _/η_ . The certificate in Section 5.2 gives error at most

[Formula on PDF page 6 (17)](../assets/figure/formula-p0006-016.jpg)

Thus _n ≥_ range( _d_ )<sup>2</sup> log(2 _/α_ ) _/_ (2 _η_<sup>2</sup> _ϵ_<sup>2</sup> ) suffices for radius _ϵ_ with these fixed weights. This is a sufficient Hoeffding bound, not an optimal sample-complexity or impossibility claim. Channel estimation adds another uncertainty source.

The sweep uses _η ∈{_ 0 _, ._ 01 _, ._ 03 _, ._ 1 _, ._ 3 _,_ 1 _}_ , calibration counts per class _c ∈{_ 40 _,_ 160 _,_ 640 _,_ 2560 _}_ , field counts 2 _c_ , and the three original population mixtures. Each of 72

# **What the logs support about the next product decision**

[Figure on PDF page 7 (4)](../assets/figure/figure-p0007-003.jpg)

Figure 2: Primary decision intervals for the known finite-bank synthetic contrast. Each row uses the same independent calibration within a domain. Markers show the evaluation-only true target. All intervals cross zero. Nominal marginal coverage is at least 96% under the stated model and sampling assumptions; this is not a simultaneous guarantee.

cells has 200 independent complete repetitions, totaling 14,400 multinomial simulations and 43,200 interval calculations. The three methods use exact _A_ with uncertain field frequencies, uncertain _A_ with exact _q_ , or uncertainty in both. The first two have 98% marginal guarantees, and the joint procedure has 96%; these are uncertainty-source ablations, not an equal-confidence ranking. Methods share samples within a repetition; repetitions and cells use independent streams. All outcomes are constructed, and no new model or human observations are generated.

For the positive mixture with _η_ = _._ 01, even _c_ = 2560 and 5,120 field observations leave every joint interval unresolved: the median width remains .10 although structural width is zero. At _η_ = _._ 1 and the same counts, field-only, calibration-only, and joint resolution rates are 98%, 54%, and 1%, respectively. The joint median width is 0.07651. These examples expose calibration and weak-signal costs; they do not identify the unknown population channels

# of the earlier LLM experiment.

All cells and repetitions are released. Coverage and resolution denominators retain infeasible cases; width quantiles condition on feasibility. There are 84 infeasible intervals and four incorrect resolutions, all in the field-only ablation. Observed field-only coverage ranges from 96% to 100% across cells, with Monte Carlo errors and exact binomial intervals reported. All joint and calibration-only intervals contain the target in these runs. A 200/200 count has a two-sided 95% binomial lower bound of approximately .982, so it is not evidence of perfect coverage. No simultaneous claim over cells is made.

## **Equal observation counts: actions and preference receipts**

Original action logs

Explicit preference receipt Known synthetic target

[Figure on PDF page 8 (6)](../assets/figure/figure-p0008-005.jpg)

Figure 3: Action-only and attribute-only intervals on the same selected task IDs. The receipt collects explicit preference information omitted from the action log; it does not discover an unobserved human preference. The follow-up was chosen after the primary results, so these are exploratory comparisons without selective-inference correction.

# **8 From telemetry to a decision receipt**

The accompanying offline viewer exposes the recorded audit to an analyst. Its selectors cover model, domain framing, field mixture, and logging condition. It displays observation counts, the known synthetic contrast, the interval, and its endpoint witness populations. The viewer renders precomputed LP results and their provenance; it neither silently reruns inference nor asks an LLM to recommend an investment. Its implementation is an inspectable prototype, with no measured usability or effect on analyst decisions.

The practical unit of measurement need not be a complete customer profile. For a declared future decision, it is enough to collect evidence about the corresponding contrast. This suggests a _decision receipt_ : a compact record of the measurement condition and the evidence

the decision actually requires. We use this term for a proposed interface artifact, not an established standard or a claim of terminology priority.

A useful receipt distinguishes an observed action, preferences explicitly supplied to the agent, an agent’s inference, and an outcome confirmed by the customer. Those sources have different evidentiary status. It records the agent and interface versions, relevant constraints, a missing-information state, and the specific decision for which the record is intended. A supplied preference does not become validated because an agent repeats it confidently. The receipt experiment tests only one minimal field, a reported leading attribute; it does not validate the entire proposed artifact.

Three design consequences follow. First, preserve the assigned measurement condition: pooling probe identities can erase the information gained from probing. Second, ask whether a cheaper measurement identifies the cur-

[Figure on PDF page 9 (3)](../assets/figure/figure-p0009-002.jpg)

Figure 4: Controlled separation of structural and statistical limitations. The figure displays the positive mixture; all three mixtures are in the released tables. Exact identification at every _η >_ 0 coexists with wide finite-sample intervals. Width summaries condition on feasibility; resolution denominators retain all repetitions. These are multinomial simulations, not additional LLM calls.

rent contrast before trying to reconstruct all preferences. Third, revisit the receipt when the decision changes. Evidence sufficient for capacity versus flexibility need not identify willingness to pay, trust, or the value of an unrelated feature. Direct, consented outcome measurement may be both more informative and simpler than recovering a latent taxonomy. The research package includes a receipt specification separating these cases, with no claim of deployed customer effectiveness.

Missing classes, preference elicitation errors, selective feedback, correlated API calls, and channel drift can invalidate calibration transport. The proofs are conditional mathematical statements. The experiment uses two snapshots and one synthetic task family, so it cannot establish a general relationship between agent capability and product-learning value. Conservative intervals can be too wide to act on; confident point estimates can obscure unmeasured uncertainty. Both costs matter.

# **9 Implications and limitations**

A valid interpretation starts with a specific product decision and outcome. Stable activity need not imply stable preference composition, and changed activity after an agent update need not imply changed demand. These are possible confoundings, not findings of widespread market failure. Calibration should record the agent, interface, prompt distribution, and time window.

The diagnostic is most useful when it makes the disagreement inspectable. A witness pair identifies which customer mixtures still fit the same declared evidence but favor different changes. That can motivate targeted, consented feedback. It does not prove that the proposed question is unbiased, cost-effective, or privacy preserving. An agent’s explanation is another potentially useful observation channel, not ground truth about its customer.

Ordinary A/B testing remains valid for measured outcomes under its assumptions. The concern is substituting agent activity for unmeasured value. If a sound experiment directly measures the relevant customer outcome, this particular gap may already be resolved. Retention and support contacts can also supply information, subject to their own timing and selection issues.

The model assumes a declared finite taxonomy, stable within-class behavior, and a meaningful contrast.

**Human validation.** No human participants were recruited, and no simulated profile is counted as a person. The released offline instrument is an investigator preview. It labels its aid as a deterministic reference chooser and its exports as non-evidence. A customer study still requires a reviewed protocol, genuine recruitment, informed consent, an independently meaningful outcome measure, and actual responses. This paper’s empirical claims are restricted to computation.

# **10 Conclusion**

Successful execution and evidence for a future product decision are distinct objectives. A calibrated channel model makes that distinction testable for a declared contrast and logging scheme. Bounds and witness populations expose what the observations leave unresolved; uncertainty accounting prevents calibration estimates from becoming unwarranted certainty. The deterministic parser and controlled channels sharpen the practical lesson: preserve useful structured input, and distinguish structural ambiguity from statistical imprecision before changing the interface or collecting more logs. The released package provides proofs, actual model traces, controls, and reproducible analysis for this task. Extending its conclusions to customers requires customer evidence.

**Availability.** Code, source, numerical records, and experiment provenance are at `https: //github.com/shi1720/delegation-blind-spot` . The repository documents limitations and venue-specific requirements. This is a technical preprint, not a claim of peer review or acceptance.

# **References**

- [1] Anastasios N. Angelopoulos, Stephen Bates, Clara Fannjiang, Michael I. Jordan, and Tijana Zrnic. Prediction-powered inference. _Science_ , 382(6671): 669–674, 2023. doi: 10.1126/science.adi6000. URL `https://arxiv.org/abs/2301.09633` .

- M. Ghassemi, and N. Chen, editors, _Advances in Neural Information Processing Systems_ , volume 38, Main Conference, pages 68727–68756. Curran Associates, Inc., 2025. doi: 10.52202/085713-2312. URL `https:`

`//proceedings.neurips.cc/paper_files/paper/ 2025/file/6389470564214983604d1ac81631c2c5Paper-Conference.pdf` .

- [11] Zachary Lipton, Yu-Xiang Wang, and Alexander Smola. Detecting and correcting for label shift with black box predictors. In Jennifer Dy and Andreas Krause, editors, _Proceedings of the 35th International Conference on Machine Learning_ , volume 80 of _Proceedings of Machine Learning Research_ , pages 3122–3130. PMLR, 2018. URL `https:`

- `//proceedings.mlr.press/v80/lipton18a.html` .

- [2] David Blackwell. Equivalent comparisons of experiments. _The Annals of Mathematical Statistics_ , 24 (2):265–272, June 1953. doi: 10.1214/aoms/1177729032.

- [3] Manuel Cherep, Chengtian Ma, Abigail Xu, Maya Shaked, Pattie Maes, and Nikhil Singh. A framework for studying AI agent behavior: Evidence from consumer choice experiments. In _International Conference on Learning Representations_ , 2026. URL `https://openreview.net/forum?id=LUrToUPS4x` .

- [4] David L. Donoho. Statistical estimation and optimal recovery. _The Annals of Statistics_ , 22(1):238–270, 1994. doi: 10.1214/aos/1176325367.

- [12] Elchin Suleymanov. A revealed preference framework for AI alignment, March 2026. URL `https://arxiv.org/abs/2603.27868` . arXiv preprint.

- [13] Tijana Zrnic and Emmanuel Candes. Active statistical inference. In Ruslan Salakhutdinov, Zico Kolter, Katherine Heller, Adrian Weller, Nuria Oliver, Jonathan Scarlett, and Felix Berkenkamp, editors, _Proceedings of the 41st International Conference on Machine Learning_ , volume 235 of _Proceedings of Machine Learning Research_ , pages 62993–63010. PMLR, 2024. URL `https: //proceedings.mlr.press/v235/zrnic24a.html` .

- [5] Noam Finkelstein, Roy Adams, Suchi Saria, and Ilya Shpitser. Partial identifiability in discrete data with measurement error. In Cassio de Campos and Marloes H. Maathuis, editors, _Proceedings of the Thirty-Seventh Conference on Uncertainty in Artificial Intelligence_ , volume 161 of _Proceedings of Machine Learning Research_ , pages 1798–1808. PMLR, 2021. URL `https://proceedings.mlr.press/v161/ finkelstein21b.html` .

- [6] Johannes Kirschner, Tor Lattimore, and Andreas Krause. Linear partial monitoring for sequential decision making: Algorithms, regret bounds and applications. _Journal of Machine Learning Research_ , 24 (346):1–45, 2023. URL `https://jmlr.org/papers/v24/22-1248.html` .

- [7] Christopher Kops and Elias Tsakas. Choice via AI, February 2026. URL `https://arxiv.org/abs/2602.04526` . arXiv preprint.

- [8] Andreas Kraft and Poet Larsen. Consumer preference transmission in agentic markets. SSRN Working Paper 6864181, June 2026. URL `https://ssrn.com/abstract=6864181` .

- [9] Tor Lattimore and Csaba Szepesvári. _Bandit Algorithms_ . Cambridge University Press, 2020. doi: 10.1017/9781108571401. URL `https://torlattimore.com/downloads/book/book.pdf` .

- [10] Puheng Li, Tijana Zrnic, and Emmanuel Candes. Robust sampling for active statistical inference. In D. Belgrave, C. Zhang, H. Lin, R. Pascanu, P. Koniusz,

# **A Proofs and extensions**

The results below make the observation assumptions explicit and provide verifiable foundations for the implementation. They are applications of established identification, convex duality, concentration, and decision-theoretic arguments, not claims of new general mathematical principles. Relevant antecedents include partial monitoring [6], partial identification under measurement error [5], optimal recovery [4], and comparison of experiments [2].

Let _A ∈_ R<sup>_m×K_</sup> be nonnegative and column-stochastic. Write _SK_ = _{p ∈_ R<sup>_K_</sup> : _p ≥_ 0 _,_ **1**<sup>_⊤_</sup> _p_ = 1 _}_ , _q_ = _Ap_ , and ∆( _p_ ) = _d_<sup>_⊤_</sup> _p_ for a fixed known vector _d ∈_ R<sup>_K_</sup> . For _q ∈ ASK_ , define

[Formula on PDF page 11 (6)](../assets/figure/formula-p0011-005.jpg)

These extrema are attained because _Pq_ is nonempty and compact. The target is a population contrast. It is not recovery of individual private preferences.

**Theorem 4** (Global and local identification) **.** _The contrast d_<sup>_⊤_</sup> _p is identified for every feasible q if and only if d ∈_ row( _A_ ) _. At a particular q, it is identified if and only if d ⊥_ span( _Pq −Pq_ ) _._

_Proof._ If _d_ = _A_<sup>_⊤_</sup> _v_ , then _d_<sup>_⊤_</sup> _p_ = _v_<sup>_⊤_</sup> _q_ for every compatible population. Conversely, if _d ∈/_ row( _A_ ), there is an _h ∈_ ker( _A_ ) with _d_<sup>_⊤_</sup> _h̸_ = 0. Column normalization gives **1**<sup>_⊤_</sup> _h_ = 0. Choose an interior _p_ 0 _∈SK_ and sufficiently small _t >_ 0 so that _p_ 0 _± th ≥_ 0. Both populations belong to the simplex, produce _Ap_ 0, and have different contrasts. The local statement follows because constancy of _d_<sup>_⊤_</sup> _p_ on _Pq_ is equivalent to orthogonality to every pairwise difference, hence to their span.

The global condition need not hold at an identified boundary point. For example, the channel with columns (1 _,_ 0)<sup>_⊤_</sup> _,_ (0 _,_ 1)<sup>_⊤_</sup> _,_ (0 _,_ 1)<sup>_⊤_</sup> cannot generally separate classes two and three, but _q_ = (1 _,_ 0)<sup>_⊤_</sup> uniquely determines _p_ = (1 _,_ 0 _,_ 0)<sup>_⊤_</sup> . This distinction prevents a rank-only test from replacing the feasible-set calculation. Observation-span conditions have direct antecedents in partial monitoring [6].

**Theorem 5** (Magnitude of the globally hidden contrast) **.** _Define_

[Formula on PDF page 11 (12)](../assets/figure/formula-p0011-011.jpg)

_Then_

[Formula on PDF page 11 (14)](../assets/figure/formula-p0011-013.jpg)

_Proof._ Every _h_ = _p − r_ in the first optimization satisfies _Ah_ = 0 and _∥h∥_ 1 _≤_ 2. Conversely, _Ah_ = 0 implies **1**<sup>_⊤_</sup> _h_ = 0. Let _h_ + _, h−_ be its positive and negative parts, with common mass _s_ = _∥h∥_ 1 _/_ 2 _≤_ 1. For any _u ∈SK_ , the vectors _p_ = _h_ + + (1 _− s_ ) _u_ and _r_ = _h−_ + (1 _− s_ ) _u_ are compatible simplex points and satisfy _p − r_ = _h_ . The feasible set is symmetric, so maximizing the absolute contrast equals maximizing the signed contrast.

For the second equality, consider

[Formula on PDF page 11 (17)](../assets/figure/formula-p0011-016.jpg)

Assign nonnegative multipliers _a, b_ to these two inequalities. Minimizing the Lagrangian over unrestricted _v_ requires _A_ ( _a − b_ ) = 0; minimizing over _t ≥_ 0 requires **1**<sup>_⊤_</sup> ( _a_ + _b_ ) _≤_ 1. The dual objective is _d_<sup>_⊤_</sup> ( _a − b_ ). Writing _z_ = _a − b_ gives precisely _Az_ = 0 _, ∥z∥_ 1 _≤_ 1: the reverse direction uses _a_ = _z_ + _, b_ = _z−_ . Primal feasibility follows by taking _v_ = 0 and _t_ = _∥d∥∞_ ; the primal is bounded below, so finite-dimensional LP strong duality applies. Rescaling _h_ = 2 _z_ proves the identity.

_W_ ( _A, d_ ) is a worst-case width over all possible _q_ ; the interval at an observed _q_ may be narrower. The dual quantity is a standard distance to an observable subspace, with conceptual antecedents in optimal recovery [4]. It is not, by itself, a measured market effect.

**Theorem 6** (Irreducible estimation and decision loss) **.** _Fix q and write L_ = _L_ ( _q_ ) _, U_ = _U_ ( _q_ ) _, and w_ = _U − L. Suppose the data consist of any finite number of iid actions from q, together with independent analyst randomization. Every estimator has worst-case mean absolute error at least w/_ 2 _and worst-case mean squared error at least w_<sup>2</sup> _/_ 4 _over Pq. If q is supplied exactly, the midpoint attains both bounds._

_If L <_ 0 _< U , the minimax customer-value regret for choosing between variants zero and one, when q is known exactly, is_

[Formula on PDF page 12 (4)](../assets/figure/formula-p0012-003.jpg)

_It is attained by choosing variant one with probability t_<sup>_∗_</sup> = _U/_ ( _U − L_ ) _. The minimax regret among deterministic decisions is_ min _{−L, U }. If the interval does not strictly straddle zero, minimax regret is zero._

_Proof._ All compatible populations yield the same data distribution. Let _T_ have the common distribution of an estimator at populations attaining the endpoints. Pointwise,

[Formula on PDF page 12 (7)](../assets/figure/formula-p0012-006.jpg)

Taking expectations bounds the larger endpoint risk from below. The constant midpoint attains both lower bounds over the whole interval when _q_ is known.

For a randomized decision rule let _t_ be its common probability of selecting variant one. Its regrets at the lower and upper endpoints are ( _−L_ ) _t_ and _U_ (1 _− t_ ), respectively; intermediate contrasts give no larger regret. Minimizing max _{_ ( _−L_ ) _t, U_ (1 _−t_ ) _}_ over _t ∈_ [0 _,_ 1] equates the terms and gives (13). Restricting _t_ to zero or one gives the deterministic result. If the interval lies weakly on one side of zero, a single variant is weakly optimal throughout.

For strict opposite-sign endpoints, the decision error probabilities are _t_ and 1 _− t_ , so their equally weighted average is 1 _/_ 2. These are fixed-channel indistinguishability statements, a standard lower-bound argument [9]. The attainability claims presume exact _q_ ; finite-sample uncertainty can add loss. A probe that changes the observation channel can break the indistinguishability.

**Theorem 7** (Coarsening) **.** _Let G be column-stochastic and set B_ = _GA. For every feasible q,_

[Formula on PDF page 12 (12)](../assets/figure/formula-p0012-011.jpg)

_The interval under B at Gq therefore contains the interval under A at q, and W_ ( _B, d_ ) _≥ W_ ( _A, d_ ) _._

_Proof. Ap_ = _q_ implies _Bp_ = _GAp_ = _Gq_ . Minimization over the enlarged set cannot increase the lower bound, and maximization cannot decrease the upper bound. Every pair with _Ap_ = _Ar_ also has _Bp_ = _Br_ , proving the global inequality.

This finite-channel implication belongs to the comparison-of-experiments viewpoint [2]. It does not establish that a more competent agent is a coarsening of another agent. That is an additional, testable relationship, not an assumption licensed by higher task success.

**Theorem 8** (A bias-aware finite-sample certificate) **.** _Let Y_ 1 _, . . . , Yn be iid categorical actions from q_ = _Ap. Choose v ∈_ R<sup>_m_</sup> _independently of these data and define ϵ_ ( _v_ ) = _∥d − A_<sup>_⊤_</sup> _v∥∞ and_ rng( _v_ ) = max _a va −_ min _a va. With probability at least_ 1 _− α,_

[Formula on PDF page 12 (17)](../assets/figure/formula-p0012-016.jpg)

_If the deployed channel is A_<sup>_′_</sup> _and_ max _k_ TV( _A_<sup>_′_</sup> _·k_<sup>_, A·k_)</sup><sup>_≤τ,theboundholdsforiiddatafromA′pafteraddingτ_rng(</sup><sup>_v_)</sup><sup>_._</sup>

_Proof._ The mean of _vYi_ under _A_ is _v_<sup>_⊤_</sup> _Ap_ . Since _p_ is a probability vector, its difference from _d_<sup>_⊤_</sup> _p_ has absolute value at most _∥A_<sup>_⊤_</sup> _v − d∥∞_ . Hoeffding’s inequality for variables in [min _a va,_ max _a va_ ] bounds the sampling deviation by the second term with probability at least 1 _− α_ . The triangle inequality proves (14).

For distributions _r, s_ , write _b_ = min _a va_ and use<sup>�</sup> _a_<sup>(</sup><sup>_ra −sa_) = 0toobtain</sup><sup>_|v⊤_(</sup><sup>_r −s_)</sup><sup>_| ≤_rng(</sup><sup>_v_) TV(</sup><sup>_r, s_).Applying</sup> this bound to every channel column and averaging over _p_ bounds the additional drift bias by _τ_ rng( _v_ ).

Minimizing the right-hand side over _v_ using only _A, d, n, α, τ_ preserves the guarantee. Choosing _v_ against the same field observations requires a separate argument. An estimated channel is not automatically a known channel; its uncertainty must be covered by a valid drift bound or the joint confidence set. Bias-aware linear estimation and concentration are established tools [4, 9].

**Theorem 9** (Identification from logged probes) **.** _Let probe e ∈{_ 1 _, . . . , E} be assigned independently of latent class with probability ρe >_ 0 _, where_<sup>�</sup> _e_<sup>_ρe_= 1</sup><sup>_,andletitschannelbeAe.Supposetheprobeidentityisrecordedandall_</sup> _probes share the same population composition p. The joint probe/action channel is B_ = vstack( _ρ_ 1 _A_ 1 _, . . . , ρEAE_ ) _, and_

[Formula on PDF page 13 (4)](../assets/figure/formula-p0013-003.jpg)

_Proof. B_ is column-stochastic and ker( _B_ ) =<sup>�</sup> _e_<sup>ker(</sup><sup>_Ae_) because every</sup><sup>_ρe_is positive.Apply Theorem 4 and orthogonal-</sup> complement identities.

If probe labels are discarded, the channel is instead<sup>�</sup> _e_<sup>_ρeAe_.Forexample,</sup><sup>_A_1=</sup><sup>_I_2and</sup><sup>_A_2equalto</sup><sup>_I_2with</sup> its rows exchanged are each fully revealing. At equal assignment probabilities their unlogged average has identical columns (1 _/_ 2 _,_ 1 _/_ 2)<sup>_⊤_</sup> . Logged experimental variation can therefore be informative when unlogged variation is not. Probe choice and its costs connect directly to experimental design and partial monitoring [6, 9].

**Proposition 10** (Continuous cost allocation for fixed weights) **.** _Suppose independent samples from probe e have size ne >_ 0 _, and fixed weights ve satisfy_<sup>�</sup> _e_<sup>_A_</sup> _e_<sup>_⊤ve_=</sup><sup>_d.Writeσ_</sup> _e_<sup>2= Var</sup><sup>_A_</sup> _e_<sup>_p_(</sup><sup>_ve,Y_)</sup><sup>_andassumeσe>_0</sup><sup>_.Theestimator_</sup> � _e_<sup>_n_</sup> _e_<sup>_−_1</sup> � _i_<sup>_ve,Y_</sup> _ei_<sup>_is unbiased, with variance_�</sup> _e_<sup>_σ_</sup> _e_<sup>2</sup><sup>_/ne.Under positive costs ceand the continuous budget_�</sup> _e_<sup>_cene_=</sup><sup>_C,_</sup> _its minimum variance and optimal allocation are_

[Formula on PDF page 13 (8)](../assets/figure/formula-p0013-007.jpg)

_Proof._ The weight identity gives unbiasedness. Independence gives the variance. Cauchy–Schwarz yields

[Formula on PDF page 13 (10)](../assets/figure/formula-p0013-009.jpg)

Equality holds at the displayed allocation.

This familiar calculation is not a new acquisition algorithm. Integer sample sizes, unknown variances, adaptive weights, or required minimum allocations need additional treatment. Zero variances require the corresponding limiting allocation or explicit minimum-count constraints.

**Proposition 11** (Rectangular uncertainty and coverage) **.** _Suppose channel columns lie in coordinate boxes_ _<u>A</u>_ _~~a~~ k_<sup>_≤_</sup> _Aak ≤ Aak, with_ 0 _≤_ _<u>A</u> ≤ A ≤_ 1 _and each containing at least one simplex vector. Frequencies lie in_ _<u>q</u> ≤ q ≤_ _<u>q.</u> Introduce Jak and impose_

[Formula on PDF page 13 (14)](../assets/figure/formula-p0013-013.jpg)

_Minimizing and maximizing d_<sup>_⊤_</sup> _p over these constraints gives attainable bounds within the supplied rectangular model. If the channel and frequency boxes cover their true values with probabilities at least_ 1 _− αA and_ 1 _− αq, respectively, the interval covers d_<sup>_⊤_</sup> _p with probability at least_ 1 _− αA − αq._

_Proof._ Every admissible ( _A, p_ ) maps to _J_ = _A_ diag( _p_ ) satisfying (15). Conversely, if _pk >_ 0, define _Aak_ = _Jak/pk_ . The resulting column sums to one and satisfies its box constraints. If _pk_ = 0, the constraints force the entire column of _J_ to zero; choose any simplex vector from that column’s nonempty channel box. These choices produce an admissible channel with frequencies<sup>�</sup> _k_<sup>_J·k_.Thisestablishesexactness,includingzero-masscolumns.</sup>

On the intersection of the two coverage events, the true pair ( _p, A_ diag( _p_ )) is feasible. Its contrast lies between the extrema. The union bound gives the asserted probability without requiring independence of the confidence events.

This confidence-set propagation is already present in the measurement-error literature, including the supplementary Proposition 1 of Finkelstein et al. [5]. An infeasible program is a failure state, not a narrow confidence interval. Fixed-sample intervals do not justify optional stopping.

**Uncertain outcomes.** If _d_ lies in an independent coordinate rectangle <u>[</u> _<u>d,</u> d_ ], sharp rectangular-model endpoints are min _p_ _<u>d⊤p</u>_ and max _p d⊤p_ over the same feasible set. This follows because _p ≥_ 0 makes the coordinate endpoints optimal for each fixed _p_ . If this outcome rectangle has error probability _αd_ , the same proof gives coverage at least 1 _− αA − αq − αd_ . Parameter correlations excluded by the rectangle can make these bounds conservative.

**Omitted classes.** A separate contamination model is needed if some customers lie outside the calibrated taxonomy. Let their mass be _η ∈_ [0 _,_ ¯ _η_ ], their total action masses be _ua ≥_ 0, and known-class masses be _zk ≥_ 0. Replace the mass and frequency constraints by

[Formula on PDF page 14 (5)](../assets/figure/formula-p0014-004.jpg)

and replace _p_ by _z_ in the channel constraints. If unknown-class contrasts lie in [ _−D, D_ ], introduce _t_ with _−Dη ≤ t ≤ Dη_ and optimize _d_<sup>_⊤_</sup> _z_ + _t_ . These constraints are linear. Every allowed contaminated model maps to these masses. Conversely, normalize nonzero known-class columns as in the proof above; when _η >_ 0, one unknown class with channel _u/η_ and contrast _t/η_ realizes the residual. At _η_ = 0, both residuals vanish. Thus the extension is exact for this broad contamination model. Merely widening an interval computed from contaminated frequencies without modifying the observation constraints does not establish such protection.

**Proposition 12** (Calibration on a fixed heterogeneous panel) **.** _For class k, let Yk_ 1 _, . . . , Yknk be independent responses to a prespecified, possibly heterogeneous prompt panel. Define_

[Formula on PDF page 14 (8)](../assets/figure/formula-p0014-007.jpg)

_For m categories and K classes, simultaneous coordinate intervals with radius_

[Formula on PDF page 14 (10)](../assets/figure/formula-p0014-009.jpg)

_cover A_<sup>¯</sup> _with probability at least_ 1 _− αA. Endpoints may be clipped to_ [0 _,_ 1] _._

_Proof._ For fixed _a, k_ , the indicators are independent variables in [0 _,_ 1], though they need not have identical expectations. Hoeffding’s inequality gives

[Formula on PDF page 14 (13)](../assets/figure/formula-p0014-012.jpg)

A union bound over all coordinates proves simultaneous coverage. Clipping to the probability range cannot exclude a true coordinate already covered.

The result targets the fixed-panel average channel, not an arbitrary deployment channel. Matching prompt composition or an explicit transport bound is still required. Alternatively, independently sampled prompts from a prespecified distribution, combined with independent stable responses, support the iid multinomial interpretation used by the benchmark’s calibration intervals. Refusals and errors must remain declared categories or enter a missing-data model. Dependence across calls or adaptive prompt selection is not covered by the elementary panel argument. Simulated profiles remain synthetic experimental inputs, irrespective of model fluency.

# **B Exploratory audit-estimator pilot**

Before the model experiment, we evaluated established audit-corrected estimators on fixed synthetic pools of 4,000 records. Five scenarios, four expected audit budgets, and five sampling policies each received 1,000 independent audit replicates, yielding 100,000 estimator evaluations. These are numerical evaluations, not model calls or people. Expected audit budgets are matched; independent Bernoulli selection makes realized counts random and their distribution is recorded.

The estimator adds an inverse-probability weighted residual correction to proxy predictions. Uniform, historicalerror active, fixed-mixture, and robust linear-path sampling use observable information; a separate oracle accesses unavailable outcome residuals. The robust-path policy adapts Li et al. [10] to a declared box uncertainty set. It is not a new method or a full reproduction of that paper’s experiments.

In the deliberately constructed strong hidden-shift case, the target contrast changes from _._ 0065 to _−._ 104 while visible records and the proxy contrast _._ 0105 stay fixed. At 100 expected audits, historical active sampling has RMSE _._ 0663 and nominal 95% Wald coverage 88.9%; uniform sampling has _._ 0577 and 93.9%; the robust-path adaptation has _._ 0558 and 93.4%. Coverage Monte Carlo standard errors are approximately 1.0, .8, and .8 percentage points. Conservative Bernstein intervals cover in all recorded runs but are often uninformative. Point-estimator unbiasedness does not guarantee adequate finite-sample Wald coverage. Two complete runs reproduce all four numerical CSV outputs byte for byte.

[Figure on PDF page 15 (4)](../assets/figure/figure-p0015-003.jpg)

Figure 5: Exploratory synthetic audit pilot. Error panels use different scales; oracle information is privileged. No claim of an effect in real delegated behavior follows from this construction.

# **C Artifact and claim audit**

[Table on PDF page 15 (7)](../assets/table/table-p0015-006.csv)

| Claim | Evidence | Limit |
| --- | --- | --- |
| Decision-specific identification | Theorems, LP witnesses, independent<br>numerical checks | Standard mathematics under a finite channel<br>model |
| Sampling and drift certificates | Full proofs, exhaustive small examples | Conditional on sampling, taxonomy, and drift<br>assumptions |
| Named model behavior | Frozen prompts and raw API records | Synthetic utilities, two model snapshots |
| Product-decision uncertainty | Held-out synthetic mixtures and de-<br>clared logging schemes | No conclusion about every possible telemetry<br>schema |
| Customer validity | Protocol and preview instrument only | No completed human study |

The source package includes pinned scientific dependencies, tests, exact preparation and analysis commands, checksums, an MIT license, and a citation file. Regenerating an API request does not guarantee an identical remote response. Offline analysis reproduces figures from the recorded responses. Public traces contain constructed inputs only and exclude credentials.
