# GEO: Generative Engine Optimization

Assigned research item 2 from the GoDaddy track briefing.
Written 2026-09-19.

The track owner flagged this explicitly and there is a live `seo.webmesh.ai` agent, so it is clearly on his mind.
He also raised the crawler tradeoff without giving a recommendation, which means an opinion is worth having.

This is the assigned item with the weakest direct tie to Hawk Eye.
It is still worth the hour, because the connection that does exist is a real one and it is not the obvious one.
Section 5 is the part that matters to us.

## 1. What GEO is, and how it grew out of SEO

Generative Engine Optimization is the practice of shaping content so that a language model selects it, cites it, and repeats it.
The adjacent term is AEO, Answer Engine Optimization; they are used near-interchangeably.

The structural difference from SEO is the reason it is dangerous, and it is a single sentence:

**SEO competes for a position in a list the user can see. GEO competes to be the answer.**

With ten blue links, a manipulated result sits next to nine others and the user does the comparison.
With a generated answer, the manipulated source becomes the sentence the user reads, stripped of provenance, delivered in the assistant's voice and inheriting the assistant's credibility.
There is no list to compare against, and frequently no visible citation at all.

GEO also attacks a different surface.
SEO targets a ranking function.
GEO targets two things at once: **the evidence pool** the model retrieves from, and **the generation step** that turns evidence into prose.
Poison either and the answer changes.

## 2. Why it is dangerous

Four properties, roughly in order of severity.

**It launders provenance.**
A manipulated page presented in an assistant's own voice loses every signal a reader uses to discount a source: the domain, the design, the ads, the tone.
The assistant's authority is transferred to content that did not earn it.

**It is cheap and it works.**
Recent measurement puts the average attack success rate across seven GEO attack methods at **50.32%** before defenses ([Wang et al., 2026](https://arxiv.org/abs/2609.02964)).
Roughly a coin flip, at the cost of rewriting a web page.

**It has industrialized.**
The literature describes the progression from manual rewriting to automated and then agentic optimization.
The thing doing the manipulating is now itself an agent, which is what makes this a track-relevant topic rather than a marketing one.

**It is nearly invisible to the victim.**
There is no ranking to inspect and no obvious tell in a fluent paragraph.
The manipulation is detectable at the retrieval layer and essentially undetectable at the reading layer.

## 3. Documented incidents

- **Microsoft, 2026**: hidden prompts embedded in "Summarize with AI" share links, written to steer assistants toward recommending particular companies. Note the shape: this is prompt injection delivered through a social-sharing affordance, which is GEO and ASI01 at the same time.
- **OECD AI Incident Monitor, 2026**: a GEO-style poisoning incident in China in which LLMs allegedly recommended fictitious or low-quality products.
- **Aurascape, 2026**: security researchers documented what they describe as the first large-scale campaign of LLM search poisoning, as opposed to isolated one-off manipulations.

The trajectory is the familiar one.
Individual actors, then tooling, then campaigns.
SEO spam took about a decade to walk that path; GEO has taken roughly two years.

## 4. Defenses, and what they cost

The best-measured published defense is **GEO Defender** ([Wang et al., 2026](https://arxiv.org/abs/2609.02964)), a two-stage approach:

1. A **Shield Reranker** learns defensive preferences over a frozen base ranker, demoting manipulated documents while preserving relevance judgments.
2. **Training-Free Shield Generation** distills defense outcomes into natural-language guidance that steers the model's source selection at inference time, with no fine-tuning of the target LLM.

Measured effect: attack success rate from **50.32% down to 6.20%**, retaining **94.12%** of benign evidence usage, and generalizing to attack methods not seen during training.

Two things are worth noticing.
The defense operates at **retrieval and source selection**, not at generation, which matches the OWASP ASI06 framing that context poisoning is fought at the context boundary rather than in the model.
And 6.20% is not zero.
A one-in-sixteen residual on a coin-flip attack is a mitigation, not a fix.

Related work along the same line includes [Counter-GEO-Bench](https://arxiv.org/abs/2609.02316), which evaluates defenses against information-distorting GEO, and [SCI-Defense](https://arxiv.org/pdf/2605.21948).

## 5. The connection to ANS, which is the part that matters

GEO is usually filed as a marketing problem.
Filed correctly, it is an **identity and provenance problem**, and that puts it on this track.

The reason GEO works is that a retrieved document carries no verifiable statement of who wrote it or whether it has changed.
A retriever chooses on textual features alone, because textual features are all there are.
That is the same failure as a self-asserted `User-Agent` header: an unbacked claim in the application layer, trusted because nothing better is available.

ANS supplies the missing primitives, and they are already built:

- **Proof of domain control** (ANS-0) makes authorship a fact rather than a claim.
- **Schema hashes in the Trust Card**, re-verified continuously by the Agent Integrity Monitor, make content drift detectable. A source that quietly rewrote itself after being cited is exactly the GEO attack, and it is exactly what `card_drift_watch` catches.
- **SCITT receipts** make "this content was what it says it was, at this time" checkable offline against the log's public key.
- **Identity grades** (Basic, Verified, Premium) give a retriever something to weight by other than prose quality. The Trust Index already weights reviews by the reviewer's identity grade and principal binding; weighting *retrieved evidence* the same way is the same idea applied one layer over.

The framing to offer:

**GEO is what happens to retrieval when sources have no identity layer. It is the same gap ANS closes for agents, showing up one layer over.**

That is a genuine contribution to the conversation rather than a summary of it, and it explains why `seo.webmesh.ai` sits in the same agent index as `fraud.webmesh.ai` instead of being an odd one out.

## 6. The crawler tradeoff, with an opinion

He raised this and gave no default, so here is one.

### The numbers

- As of June 2026, bots generate **57.5% of HTML web traffic**. Automated requests have overtaken human ones for the first time.
- Per Cloudflare, **AI training accounts for 52% of crawler requests** as of June 2026, with mixed-use crawlers above 36%.
- As of **September 15, 2026**, Cloudflare blocks mixed-use crawlers by default on ad-carrying pages for new customers, new sites, and every free-tier site.

### The opinion

**Block training crawlers. Allow answering crawlers. Never block by category, and never use `robots.txt` as though it were an access control.**

Three reasons.

**The bandwidth and the benefit come from different bots.**
The load is overwhelmingly training crawlers, which return nothing.
The citations come from search and answering crawlers, which return qualified referrals.
GPTBot is not OAI-SearchBot; ClaudeBot is not Claude-SearchBot.
Treating them as one category forces a choice between paying for traffic that never converts and disappearing from the surface that increasingly mediates discovery.
Split them and the choice disappears.

**Blocking everything is a GEO own-goal.**
If a site is absent from the evidence pool, the answer still gets generated.
It gets generated from whatever is left, which now includes whoever optimized hardest.
Abstaining from the index does not protect a site from GEO; it removes the one source that had an interest in being accurate.

**`robots.txt` is a request, not a control.**
Given a 2.4% fraudulent-PerplexityBot rate in DataDome's 2026 data, an honor-system directive is worth exactly what the requesting party's honesty is worth.
Anything that matters needs verified identity at the edge.

Which is the point to land on, because it closes the loop:

**The crawler tradeoff is only a tradeoff because crawler identity is unverifiable.**
Once a crawler can prove who it is, "block training, allow answering" stops being a guess based on a string the crawler chose for itself and becomes an enforceable policy.
That is an ANS argument, and it is a better answer to his open question than picking a side.

## Sources

- [When Optimization Becomes Manipulation: Defending Generative Search against Malicious Generative Engine Optimization](https://arxiv.org/abs/2609.02964)
- [Counter-GEO-Bench: Evaluating Defenses Against Information-Distorting Generative Engine Optimization](https://arxiv.org/abs/2609.02316)
- [SCI-Defense: Defending Manipulation Attacks from Generative Engine Optimization](https://arxiv.org/pdf/2605.21948)
- [Position: Generative Engine Optimization Creates Underexamined Risks](https://arxiv.org/html/2606.12439)
- [How Much Can We Trust LLM Search Agents? Measuring Endorsement Vulnerability to Web Content Manipulation](https://arxiv.org/pdf/2606.16821)
- [robots.txt across Cloudflare's network, September 2026 update](https://technologychecker.io/blog/robots-txt-ai-crawlers-blocking-report)
- [AI crawler and bot traffic statistics, 2026](https://www.digitalapplied.com/blog/ai-crawler-bot-traffic-statistics-2026-data-reference)
