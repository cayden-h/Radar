# The incident types

Researched 2026-09-19. Every figure here was verified during that session; sources are linked inline.
Use these numbers in the pitch, the Devpost page, and the video. Do not round them upward.

Hawk Eye covers **Fire** and **Burglary**.
It covered a third, **Faint**, until 2026-09-19. That section is kept below, as history, and it is marked as history.
Read the synthesis at the bottom of each section; the raw numbers matter less than what they imply about the product.

**The headline is responsiveness.**
Responders arriving at a building do not know who is inside or whether those people can answer.
Hawk Eye tells them: which rooms hold a presence, and how long since a breathing signature that was there stopped being resolvable.
That is a narrower claim than the one this file used to lead with, and unlike that one it survives contact with what the radio can actually measure.

---

## Faint / fall - cut as an incident type on 2026-09-19

**Read this section as history, not as a capability.**

Faint was the third incident type and fall detection was the feature behind it. Both were cut on 2026-09-19, and `agents/people/collapse.py` was deleted.
**The system does not detect falls, does not measure time on the floor, and must never be pitched as doing either.**

Why it went: debounce was the whole engineering problem and it never got better.
Sitting down fast, lying down to sleep and a child playing all look like a fall for an instant, and a system that calls 911 when someone flops onto a couch is worse than no system.
It was a debounce problem dressed as a clinical variable.

The figures below are real, sourced, and were the motivation for the original design. They are kept for exactly that reason: a scope cut you cannot explain is a scope cut you cannot defend, and a judge who asks "why not falls, the statistics are right there" deserves the statistics and the answer together.
Two of them still do work in the current pitch and are cited elsewhere: how many older adults live alone, and the fire timeline in the next section.

### Scale

- **43,020 deaths** among adults 65+ from preventable falls in 2024.
- **Over 3.85 million** emergency department visits for fall-related injuries in 2023.
- Roughly **4.5 million ED visits per year**: 3.1 million treated and released, 1.4 million hospitalized.
- Fall deaths among older adults are **up 51% over ten years**; ED visits up 38%.
- **More than one in four** older adults reports a fall each year.

Sources: [CDC Older Adult Falls](https://www.cdc.gov/falls/data-research/facts-stats/index.html), [NSC Injury Facts](https://injuryfacts.nsc.org/home-and-community/safety-topics/older-adult-falls/), [NCOA](https://www.ncoa.org/article/get-the-facts-on-falls-prevention/)

### The long lie

A **"long lie"** is clinically defined as being unable to get up from the floor for more than one hour after a fall.

- In a prospective cohort of 1,610 older fall cases, **over 53% were still on the floor when the ambulance arrived.**
- In a study of 125 adults over 65, **half of those who lay on the floor for more than an hour died within six months**, even where the fall itself caused no direct injury.
- Complications from prolonged floor time: pressure ulcers, rhabdomyolysis, pneumonia, hypothermia, dehydration.
- Long-lie patients were more likely to suffer subsequent serious injury, hospital admission, and entry into long-term care.

Sources: [BMJ prospective cohort, people over 90](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2590903/), [CCMC on long lie complications](https://ccmcertification.org/courses/complications-resulting-long-lie-times-after-fall), [Physiopedia: Long Lie](https://www.physio-pedia.com/Long_Lie)

### Who is alone when it happens

- **28% (16.2 million)** of community-dwelling older adults live alone.
- **22% of older men, 33% of older women.**
- Among women **75 and older, roughly 42% live alone.**

Sources: [Merck Manual](https://www.merckmanuals.com/professional/geriatrics/social-issues-in-older-adults/older-adults-living-alone), [Pew Research](https://www.pewresearch.org/short-reads/2025/12/04/a-smaller-share-of-older-us-adults-live-alone-today-than-in-1990/)

### Synthesis, as of the cut: what survived and what did not

**What did not survive: every claim in this section that depends on knowing a fall happened.**
The long lie is defined by time on the floor after a fall. Nothing in the shipped system detects a fall, so nothing in it can measure a long lie, and no pitch, deck or Devpost line may imply otherwise.

**What survived is the shape of the insight rather than its subject.**
The figures above are a mortality curve driven by *how long it took someone to find them*, and 53% still on the floor at ambulance arrival says discovery time is already too slow even for people whose calls were made.
The general form of that - the information that decides the outcome is missing at the moment of the call - is still true, and it is still what this project is about.

What the system measures instead is responsiveness: **when a human does call, the dispatcher learns which rooms hold a presence, and how long since a breathing signature that was resolvable there stopped being resolvable.**
That is `people.respiration_lost`. It is a measurement and a clock, it is stamped from the last resolvable signature rather than from when the agent became confident, and it is never a finding that someone has stopped breathing.

Today that information does not exist either. Responders arrive at a building knowing nothing about who is inside.
That claim is defensible, it is specific, and it does not require claiming either an autonomy or a detector we deliberately did not build.

---

## Fire

### Scale

- A home structure fire was reported **every 96 seconds** in 2024.
- A home fire death occurred **every 3 hours**; a home fire injury **every 59 minutes**.
- **3,920 civilian fire deaths in 2024**, up 6.8% from 3,670 in 2023.
- One- and two-family homes account for **65.8% of civilian fire deaths** and 56.3% of injuries.
- Five-year average (2019-2023): **2,600 civilian deaths, 10,770 injuries, $8.9 billion** in direct property damage annually.
- The 2024 death rate of **8.9 per 1,000 reported home fires is 25% higher than 1980's 7.1**, despite decades of smoke alarm adoption.

Sources: [NFPA Home Structure Fires](https://www.nfpa.org/education-and-research/research/nfpa-research/fire-statistical-reports/home-structure-fires), [NFPA Fire Loss in the US](https://www.nfpa.org/education-and-research/research/nfpa-research/fire-statistical-reports/fire-loss-in-the-united-states), [USFA Statistics](https://www.usfa.fema.gov/statistics/)

### What actually kills people

- **Smoke inhalation alone accounts for 35% of residential fire fatalities. Thermal burns alone account for 6%.**
- Smoke inhalation is implicated in roughly 50-80% of fire deaths overall.
- Carbon monoxide binds hemoglobin and causes hypoxia; hydrogen cyanide blocks cellular respiration outright.
- **Toxic gases can render a person unconscious in under a minute, often before they are aware there is a fire.**

### How little time there is

- NFPA: as little as **one to two minutes to escape** once the smoke alarm sounds.
- A room furnished with **legacy materials took over thirty minutes** to become life-threatening.
- A room with **modern furnishings becomes unsurvivable in under three minutes.**

Sources: [USFA Civilian Fire Fatalities in Residential Buildings](https://www.usfa.fema.gov/downloads/pdf/statistics/v21i3.pdf), [NFPA escape planning](https://www.nfpa.org/education-and-research/home-fire-safety/escape-planning), [Cleveland Clinic](https://health.clevelandclinic.org/house-fires-why-there-is-danger-beyond-the-flames)

### Synthesis: the occupant is unconscious before they know

The whole design of the air-quality reading in `agents/master` and the decision to take fire as an external input rather than detect it falls straight out of this data.

**Nobody needs us to tell them the house is on fire.** The smoke alarm does that, the occupant does that, the neighbor does that.
What nobody knows, including the arriving crew, is **how many people are still inside, where they are, and which of them will answer.**

And the reason they cannot simply be asked is in the numbers: unconscious in under a minute, often before awareness, in a room that becomes unsurvivable in three.
The person who would have answered the door, pressed the button, or shouted from a window is already down.

This also justifies carbon monoxide as the environmental signal over any other choice. CO is the mechanism, not a proxy for it.

---

## Burglary

### Scale

- **779,542 burglaries** recorded by the FBI in 2024.
- **405,776 were residences**, 52% of the total.
- **216,601 daytime** residential burglaries versus **174,053 nighttime**.
- National rate **229.2 per 100,000** in 2024, down from 253.3 in 2023 and **down 69% from 2005**.
- Burglary fell 8.6% year over year; residential burglary reports fell a further 19% in the first half of 2025.

Sources: [FBI via MoneyGeek](https://www.moneygeek.com/resources/home-burglary-statistics/), [Statista burglary rate](https://www.statista.com/statistics/191243/reported-burglary-rate-in-the-us-since-1990/), [SafeHome](https://www.safehome.org/resources/burglary-statistics/)

### Synthesis: the honest one

**Be careful with this incident type. The trend is strongly downward and a judge may know that.**
Do not present burglary as a growing crisis; it is not. Present it as the case that demonstrates a capability the other two do not.

The interesting figure is that **daytime residential burglaries outnumber nighttime ones**, 216,601 to 174,053.
Burglars prefer empty houses, which means the dangerous cases are the minority where someone is home and the burglar did not expect it.

That is precisely the scenario Hawk Eye addresses and existing systems do not:
a motion sensor tells you something is moving; it cannot tell responding officers **where the intruder is and where the resident is, as separately tracked presences.**

That distinction is the demo, and it is why burglary stays in the roster despite being the weaker of the two on raw numbers.

---

## Swatting, for the ANS argument

Not an incident type we cover. It is the threat model for `agents/caller`.

- **No central agency historically tracked swatting**, so there is no clean annual figure. Say this rather than inventing one.
- The ADL estimated roughly **1,000 incidents per year** as of 2019.
- The FBI launched the **National Common Operating Picture (NCOP) database in May 2023**; over **300 incidents May-September 2023** and **550+ since inception**.

Sources: [The Hill on the FBI database](https://thehill.com/blogs/blog-briefing-room/4075617-fbi-launches-national-swatting-database-amid-rising-incidents/), [NBC News](https://www.nbcnews.com/news/us-news/fbi-formed-national-database-track-prevent-swatting-rcna91722)

**How to use it:** swatting motivates the problem. It is not something Hawk Eye prevents.
The honest claim is attribution after the fact, via `agents/replay` and the SCITT log. See `agents/CLAUDE.md`.
The fact that the FBI only began counting in 2023 is itself a useful point: the baseline is unmeasured because nobody could attribute these calls.
