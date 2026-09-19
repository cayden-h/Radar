# The three incident types

Researched 2026-09-19. Every figure here was verified during that session; sources are linked inline.
Use these numbers in the pitch, the Devpost page, and the video. Do not round them upward.

Hawk Eye covers **Fire**, **Burglary**, and **Faint**.
Read the synthesis at the bottom of each section; the raw numbers matter less than what they imply about the product.

---

## Faint / fall

**This is the strongest of the three, and it is not close.**
If the pitch only has room for one incident type, use this one.

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

### Synthesis: the long lie is the thing we actually fix

**The fall is rarely what kills. The time on the floor is.**

Half of long-lie patients dead within six months, with no injury from the fall itself, is a mortality figure driven entirely by *how long it took someone to find them.*
53% still on the floor at ambulance arrival says the current system's discovery time is already too slow, and that is for people whose calls were made.

**What Hawk Eye does and does not claim here.** Settled 2026-09-19: it does not call 911 by itself. A human does.

So the claim is not that it summons help for an unconscious person. It is narrower and still worth having:

**When a human does call, the dispatcher learns how long the person has been down, which room they are in, and whether they are breathing.**

Today that information does not exist. A caller who finds someone on the floor cannot say whether it happened four minutes or four hours ago, and the literature says that interval is the variable that predicts the outcome.
`still_down_s` is a timestamp nobody has ever been able to give a dispatcher, and it is the clinical variable.

Lead with that. It is defensible, it is specific, and it does not require claiming an autonomy we deliberately did not build.

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
What nobody knows, including the arriving crew, is **how many people are still inside and where.**

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

That distinction is the demo, and it is why burglary stays in the roster despite being the weakest of the three on raw numbers.

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
