"""Exam board marking guidance, compiled into one prompt block for the marker.

Cambridge and Edexcel each publish general marking principles and command word
definitions their examiners work to, and there are conventions below that per
subject family, per subject and per paper. None of it reached the marker before
this module: `exam_board` was never passed to the marking prompt, so the same
handwritten page was marked identically whether it was Cambridge O Level 5090
or Edexcel IGCSE 4BI1.

The layers, general to specific:

    board principles -> command words -> subject family -> subject -> paper

**Authority is not equal across those layers, and the block says so.** The
official mark scheme for the paper decides any mark it covers — every layer
here is subordinate to it. Board principles and command words are the board's
own published standard. The family, subject and paper layers are *tutor
supplied*: useful operational detail, but assembled by the tutor rather than
transcribed from a board document, so the prompt labels them that way and the
marker is told to flag a conflict for review rather than silently pick a side.

Paper-level guidance resolves only for past papers — `PastPaper.paper_number`
exists, `Assignment` and `Classified` have no paper number — the same
restriction that applies to examiner reports.

These are reference data, identical for every tutor, so they live here as
constants rather than in a table: a change to them is a change to how marks are
awarded and belongs in a reviewed diff, not in a row a tutor can edit away. A
tutor's own preferences remain a separate, more local layer in their Knowledge
Base (services/knowledge.py).

**Editing any text in this file is a meaningful change to the marking prompt,
so bump the `marking` prompt version in services/prompts.py when you do.** That
is what keeps QuestionMark.ai_prompt_version honest: without the bump, two rows
both stamped the same version could have been marked under different guidance.
Which *board* applied is always recoverable from the data (submission -> group
-> subject -> exam_board), so only the text needs the discipline.

The functions here are pure — plain strings in, one string out, no database —
so they unit-test without a session, the same way the Readiness Engine's
scoring functions do.
"""

BOARD_CAMBRIDGE = "cambridge"
BOARD_EDEXCEL = "edexcel"


def normalize_board(exam_board: str) -> str | None:
    """Resolve a free-text `Subject.exam_board` to a board key, or None.

    `exam_board` is an unconstrained String(64), and a tutor-uploaded syllabus
    fills it from an AI-drafted value (services/syllabus_extraction.py), so the
    seeded "Cambridge O Level" / "Edexcel IGCSE" are conventions rather than
    guarantees — "CAIE", "Pearson Edexcel" and bare "cambridge" all turn up.
    Matching on substrings absorbs that.

    Returning None for anything unrecognised is deliberate: a board we cannot
    identify gets no guidance at all rather than another board's, because
    marking a Cambridge script to Edexcel's rules is worse than marking it to
    none.
    """
    if not exam_board:
        return None
    board = exam_board.casefold()
    if "cambridge" in board or "caie" in board:
        return BOARD_CAMBRIDGE
    if "edexcel" in board or "pearson" in board:
        return BOARD_EDEXCEL
    return None


# --------------------------------------------------------------------------
# Layer 1 — the boards' published general marking principles
# --------------------------------------------------------------------------

CAMBRIDGE_PRINCIPLES = """Cambridge general marking principles — the standard every Cambridge \
mark is held to:
1. Marks must follow the specific content, skills and standard of response shown in the mark \
scheme or level descriptors.
2. Marks awarded must always be whole numbers, never fractions or half marks. Do not reason in \
half marks and then round — decide the whole mark the response has earned.
3. Marking must be positive: reward what the candidate knows and can do. Never deduct marks for \
errors or omissions elsewhere in the answer.
4. Apply the scheme's rules and level descriptors consistently across every candidate and every \
question.
5. Use the full range of marks the scheme defines when the quality of the work merits it — full \
marks for an answer that matches the scheme, and no marks for one the scheme gives no credit to.
6. Base marks solely on the mark scheme's requirements, completely independent of grade \
thresholds, predicted grades or general grade descriptors. What grade this mark leads to is \
never a reason to change it."""


EDEXCEL_PRINCIPLES = """Edexcel general marking principles — the standard every Edexcel mark is \
held to:
- All candidates receive the same treatment. Mark the first candidate exactly as you mark the \
last; the same response earns the same mark every time.
- Apply the mark scheme positively. Reward candidates for what they have shown they can do \
rather than penalising them for omissions.
- Mark according to the mark scheme, not according to where you think grade boundaries lie.
- There is no ceiling on achievement. All marks on the mark scheme should be used \
appropriately.
- Every mark on the scheme is designed to be awarded. Award full marks when the answer matches \
the scheme, and award zero when the response earns no credit under the scheme — but see the \
rule below on answers you cannot find.
- Where the scheme requires judgement it gives the principles by which marks are awarded, and \
its exemplification may be limited; apply the principle rather than looking for an exact match \
to the example.
- When you are in doubt about how the mark scheme applies to a response, the tutor decides — \
they are the team leader here. Set confidence 'low' so the question reaches their review queue \
with your reasoning attached. Do not resolve the doubt yourself by guessing a mark.
- Crossed-out work should be marked UNLESS the candidate has replaced it with an alternative \
response. If they crossed something out and wrote a replacement, mark the replacement."""


#: Mark scheme notation both boards share. Kept board-neutral because it is a
#: property of how schemes are written, not of one subject — it arrived filed
#: under Cambridge Biology, which would have loaded it for biologists only.
MARK_SCHEME_CONVENTIONS = """Reading the mark scheme's own notation:
- A phrase the scheme marks "ignore" is harmless extra material. It neither earns credit nor \
costs any — do not let it reduce a mark the rest of the answer has earned.
- A phrase the scheme marks "reject" actively cancels the point it belongs to, even when the \
surrounding wording is otherwise creditworthy.
- Wording that only restates the question, or adds generic filler such as "to make it precise" \
or "to get an accurate result", earns nothing on its own. Ignore it rather than penalising it."""


ZERO_RULE = """Awarding zero, and when not to:
- A question the student attempted that earns no credit under the mark scheme scores 0. That is \
a real mark and it counts — award it.
- A question the student left blank scores 0 **only when you are certain it was genuinely not \
answered**: the page where that answer belongs is present and legible, and the space for it is \
empty. Then 0 is correct and confident.
- If you cannot be certain the answer is absent — pages look missing from the upload, the answer \
might be continued elsewhere, handwriting is illegible, an image is cropped or unclear — this is \
NOT a zero. Return no mark for that question and set confidence 'low' so the tutor sees it. \
"I could not find it" and "they did not answer it" are different findings and must not be \
reported as the same mark.
- Never score 0 to represent your own uncertainty. A wrong 0 is recorded as the student having \
failed that topic and drags their readiness down with no human checking it, so when in doubt \
leave the mark unset and flag it."""


BOARD_PRINCIPLES: dict[str, str] = {
    BOARD_CAMBRIDGE: CAMBRIDGE_PRINCIPLES,
    BOARD_EDEXCEL: EDEXCEL_PRINCIPLES,
}


# --------------------------------------------------------------------------
# Layer 2 — command words
#
# What a command word demands decides how much an answer must do to earn the
# mark: an answer that "states" where the question said "explain" is not full
# marks. Cambridge publishes these definitions; Edexcel's are not loaded yet,
# and an absent entry simply omits the section rather than substituting the
# other board's.
# --------------------------------------------------------------------------

CAMBRIDGE_COMMAND_WORDS = """Cambridge command words — what each one requires of an answer. \
Judge the response against the demand of the command word actually used in the question:
- Analyse: examine in detail to show meaning, and identify elements and the relationship \
between them
- Assess: make an informed judgement
- Calculate: work out from given facts, figures or information
- Comment: give an informed opinion
- Compare: identify/comment on similarities and/or differences
- Consider: review and respond to given information
- Contrast: identify/comment on differences
- Define: give a precise meaning
- Describe: state the points of a topic / give characteristics and main features
- Develop: take forward to a more advanced stage or build upon given information
- Discuss: write about issue(s) or topic(s) in depth in a structured way
- Evaluate: judge or calculate the quality, importance, amount or value of something
- Explain: set out purposes or reasons / make the relationships between things clear / say why \
and/or how and support with relevant evidence
- Give: produce an answer from a given source or recall/memory
- Identify: name/select/recognise
- Justify: support a case with evidence/argument
- Outline: set out the main points
- Predict: suggest what may happen based on available information
- Sketch: make a simple freehand drawing showing the key features, taking care over proportions
- State: express in clear terms
- Suggest: apply knowledge and understanding to situations where there are a range of valid \
responses to make proposals/put forward considerations
- Summarise: select and present the main points, without detail"""


COMMAND_WORDS: dict[str, str] = {
    BOARD_CAMBRIDGE: CAMBRIDGE_COMMAND_WORDS,
}


# --------------------------------------------------------------------------
# Layer 3 — subject family
#
# Cambridge publishes science-wide marking rules that apply across its science
# syllabuses, so they sit between the board layer and the individual subject
# rather than being duplicated into each.
# --------------------------------------------------------------------------

CAMBRIDGE_SCIENCE = """Cambridge science marking rules — these apply across the science \
syllabuses:
1. Consider the context and scientific use of any keyword before crediting it. A keyword that is \
present but used incorrectly does not earn the mark.
2. Do not choose between contradictory statements in the same question part. Where the answer \
contradicts itself, the contradicted point earns nothing. Wrong science that is irrelevant to \
the question is ignored rather than penalised.
3. Spelling need not be correct, but the spelling of a syllabus term must clearly and \
unambiguously distinguish it from other syllabus terms it could be confused with (ethane/ethene, \
glucagon/glycogen, refraction/reflection).
4. Apply error carried forward (ecf) where appropriate: if an incorrect earlier value is then \
used in a scientifically correct way, award the subsequent marking points. The mark scheme notes \
any exception.
5. Questions asking for a set number of responses ("state two reasons"): read the response as \
continuous prose even when numbered spaces are given. Anything the scheme says to ignore does not \
count towards the number; incorrect responses earn nothing but do count towards it. Read the \
whole response for contradictions — two responses that contradict each other are treated as one \
incorrect response. Non-contradictory responses beyond the number asked for may be ignored.
6. Calculations: a correct answer earns full credit even with no working or incorrect working, \
unless the question says to show working. Where the required number of significant figures is not \
stated, credit a correct answer rounded to the number of significant figures in the mark scheme \
(this may not apply to measured values). Standard form that does not restrict the coefficient to \
between 1 and 10 may still earn credit if it converts to the scheme's answer. Unless a separate \
mark is given for the unit, a missing or incorrect unit normally costs the final calculation \
mark.
7. Chemical equations: multiples or fractions of coefficients are acceptable unless the scheme \
says otherwise. State symbols in an equation are ignored unless the question asks for them or the \
scheme says otherwise.
8. Where a question requires a formula, look for the values substituted into it. Substituting \
into an incorrectly rearranged formula loses the method credit that a correct substitution would \
have earned."""


#: Which family a subject belongs to, keyed (board key, `Subject.code`).
SUBJECT_FAMILY: dict[tuple[str, str], str] = {
    (BOARD_CAMBRIDGE, "5070"): "science",
    (BOARD_CAMBRIDGE, "5090"): "science",
}


FAMILY_GUIDELINES: dict[tuple[str, str], str] = {
    (BOARD_CAMBRIDGE, "science"): CAMBRIDGE_SCIENCE,
}


# --------------------------------------------------------------------------
# Layer 4 — subject
#
# Keyed on `Subject.code` rather than `name` because a code is board-scoped and
# stable ("4MA1", "5090") while names drift ("Mathematics A"). A subject with no
# entry still receives every layer above it.
#
# Tutor-supplied operational detail. Rules that depend on reading handwritten
# notation precisely — subscript and superscript placement, bracket rendering,
# whether a bond line touches the right atom — are deliberately NOT included:
# the marker reads photographs of handwriting, where those render unreliably,
# and a false negative costs a student marks with no human in the loop.
# --------------------------------------------------------------------------

CAMBRIDGE_5070_CHEMISTRY = """Cambridge O Level Chemistry 5070 — subject conventions:
1. Element symbols use standard capitalisation, and a symbol whose capitalisation makes it a \
different element (Co for cobalt written as CO) is incorrect chemistry. Judge this only where the \
handwriting is clearly legible; where the capitalisation is genuinely ambiguous on the page, do \
not penalise it.
2. Equations: fractional or doubled coefficients are acceptable unless the question demands the \
lowest whole-number ratio. State symbols are ignored by default, but are required and separately \
credited for equations defining enthalpy changes, and wherever the question says "including state \
symbols".
3. Ionic equations: spectator ions should not appear. An equation left with a spectator ion has \
not answered what was asked, even when it balances.
4. Calculations: a correct final answer earns the full marks for the question even with no \
working, unless the question says to show working. Intermediate steps rounded hard (to one or two \
significant figures) usually corrupt the final value — where the final answer is outside the \
scheme's range because of premature rounding, the earlier method marks still stand. Error carried \
forward applies, except where the earlier step produced a physically impossible value such as a \
negative number of moles or a yield above 100%.
5. Qualitative analysis observations must use the syllabus's own vocabulary. "Precipitate" (or \
"ppt") is required rather than "cloudy", "milky" or "solid forms"; "effervescence", or bubbles \
or gas evolved together with the identifying test for that gas, is required rather than "fizzing" \
or "gas is seen". When sodium hydroxide or aqueous ammonia is added to test for cations, the \
observation is incomplete without what happens when the reagent is added in excess. Colours must \
match the scheme's specificity — "light green" and "light blue" are not interchangeable with \
loose descriptions.
6. Organic nomenclature distinguishes homologous series by a single letter: ethane and ethene, \
propanol and propanal, are different compounds and are not treated as spelling slips. In the test \
distinguishing alkanes from alkenes, bromine water turns colourless, not "clear".
7. The list principle: where a question asks for one item and the response gives a correct one \
alongside an incorrect one, the incorrect item cancels the correct one.
8. Explaining low boiling points of simple covalent substances requires the weak intermolecular \
forces (forces between molecules) to be overcome. Saying that covalent bonds break, or that bonds \
between atoms are weak, does not earn the mark."""


CAMBRIDGE_5090_BIOLOGY = """Cambridge O Level Biology 5090 — subject conventions:
1. Phonetic misspelling is acceptable only where it cannot be confused with another biological \
term. Terms that name a different structure or molecule are not spelling slips: glycogen and \
glucagon, ureter and urethra, adenine and adenosine, mitosis and meiosis.
2. Precise terms are required where the syllabus defines them. "The type of gene" does not earn \
the mark for allele, and "pure-breeding" does not earn homozygous, in genetics questions.
3. Location matters in process questions: transcription occurring "in the cell" is not the same \
answer as "in the nucleus".
4. Osmosis: the answer needs the direction of water movement across a partially permeable \
membrane, described in the syllabus's own terms. Omitting the membrane leaves the mechanism \
unexplained.
5. Active transport: "uses energy" is usually not enough. The answer needs energy from \
respiration, or ATP, moving a substance against a concentration gradient.
6. Enzymes are denatured by high temperature, with the active site changing shape so the \
substrate no longer fits. An enzyme described as "killed" or "destroyed" has not answered the \
question.
7. Biological drawings: lines must be sharp, continuous and single — feathery, sketchy or \
overlapping lines lose the drawing-quality mark. Stipple shading, cross-hatching and colouring \
are not credited. A structural layer with real thickness, such as a cell wall or an epidermis, \
is drawn with double lines."""


EDEXCEL_4CH1_CHEMISTRY = """Edexcel International GCSE Chemistry 4CH1 — subject conventions:
1. Edexcel schemes label marking points M1, M2, M3. Where a scheme notes that a point is \
dependent on an earlier one, the later point cannot be awarded if the earlier statement is \
missing or chemically wrong, however well the later point is phrased.
2. Reactions of lithium, sodium and potassium with water need specific visual observation: \
effervescence, fizzing or bubbles rather than "gas is given off". For sodium and potassium, the \
metal melting into a ball and moving or darting across the surface is part of the observation.
3. Titration indicator colour changes must be stated in the correct direction for the titration \
actually performed — which reagent is in the flask decides the direction. Describing the endpoint \
as "clear" or "neutral" does not earn the mark.
4. Titration calculations use a mean of concordant titres only. Including a rough or \
non-concordant titre in the mean loses the calculation mark. Burette readings in a results table \
are recorded to two decimal places, ending in .00 or .05.
5. Paired definitions need both halves. "Unsaturated hydrocarbon" requires the carbon-to-carbon \
double bond and a compound of hydrogen and carbon only — the word "only" is load-bearing. Dynamic \
equilibrium requires both that the forward and reverse reactions occur at the same rate and that \
concentrations of reactants and products remain constant.
6. Polyatomic groups in a formula need their brackets: Mg(OH)2 and MgOH2 are different claims \
about the compound.
7. An equation for catalytic cracking must show at least one alkane and one alkene among the \
products. Products that are only alkanes, or only hydrogen, do not represent cracking."""


EDEXCEL_4BI1_BIOLOGY = """Edexcel International GCSE Biology 4BI1 — subject conventions:
1. Edexcel schemes label marking points M1, M2, M3. Where a scheme notes a point is dependent on \
an earlier one, the later point cannot be awarded if the earlier one is missing, vague or wrong. \
Where a scheme offers more marking points than the question is worth, credit up to the maximum — \
but a point contradicted elsewhere in the response cancels the point it contradicts.
2. Experimental design answers are marked against CORMS, and a missing element costs the mark it \
carries: C — the independent variable being changed, named with specific values or a range, not \
just "change the temperature"; O — a biological feature of the organism held constant (same \
species, same age, same mass); R — repeats, with a number or a stated sample size and a mean, not \
just "repeat the experiment"; M — both what dependent variable is measured and how or over what \
time it is measured; S — two named controlled variables and how each is controlled.
3. Phonetically clear misspelling is accepted only where it cannot be confused with another term. \
Glycogen and glucagon, ureter and urethra, adenine and adenosine, mitosis and meiosis are \
different answers, not spelling slips.
4. Red blood cells lacking a nucleus provide more space for haemoglobin. "More surface area" does \
not earn this mark — the biconcave shape is what gives the surface-area-to-volume ratio.
5. Denaturation requires the active site changing shape so the substrate is no longer \
complementary and cannot form an enzyme-substrate complex. "The enzyme changes shape" is not \
enough for an explanation mark, and an enzyme "killed" or "dying" does not earn it.
6. Osmosis answers need water moving across a partially permeable membrane, with the direction \
stated. Omitting the membrane leaves the mechanism unexplained.
7. Stomatal opening follows a sequence: guard cells absorb water by osmosis, become turgid, and \
because the inner wall is thicker and less flexible than the outer wall they curve apart to open \
the pore. The wall-thickness detail carries a mark.
8. Genetic cross diagrams need four distinct tiers to earn full marks: parental phenotypes and \
genotypes; gametes, clearly separated; offspring genotypes; and offspring phenotypes matched to \
those genotypes. A bare ratio such as "3:1" does not answer a question asking for a phenotypic \
ratio — the traits must be named ("3 tall : 1 short"). Sex-linked alleles are written as \
superscripts on the X and Y chromosomes, not as standalone letters.
9. Energy loss between trophic levels needs the pathway, not "lost in waste": heat from \
respiration, egestion or excretion, or parts of the organism not eaten. Animals release carbon \
dioxide by respiration. Decomposers are fungi and bacteria secreting extracellular enzymes, \
releasing carbon dioxide through their own respiration.
10. Describing a trend from a graph earns little without data: quote coordinates from the graph \
with their values and units rather than saying a quantity "goes up".
11. The list principle: where a question asks for one item and the response gives a correct one \
alongside an incorrect one, the incorrect item cancels the correct one.
12. Teleological phrasing does not earn credit. Adaptation is not something an organism chose — \
the answer needs mutation, selective advantage, survival, reproduction and the allele being \
passed on."""


EDEXCEL_4MA1_MATHS = """Edexcel International GCSE Mathematics A 4MA1 — subject conventions:
1. Marks are of three kinds and interact: M (method) marks for a correct, recognisable method \
with appropriate values, which a minor arithmetic slip does not invalidate; A (accuracy) marks \
for a correct answer arising from a correct method, lost automatically if the method mark it \
depends on is lost; B marks for a specific correct answer, notation or geometric reason, \
independent of method.
2. A correct final answer earns the marks for the question. Working is required only where the \
question demands it — "show that", "show clear algebraic working", or "without the use of a \
calculator" — and there a correct answer without the steps earns nothing.
3. Premature rounding of intermediate values corrupts the final answer. Where the final value \
falls outside the scheme's stated range because of it, the accuracy mark is lost while the method \
marks stand. Accuracy marks written as a range are satisfied by any value inside the range and \
none outside it.
4. Follow through: an arithmetic error in one part that is then used correctly in a later part \
costs the accuracy mark where it was made, not the method marks in the parts that follow.
5. "Form an equation" requires an equals sign. An expression such as 3x + 5 does not answer it; \
it must be set equal to something. Where the question asks for simplification, a fraction, ratio \
or expression left unsimplified does not earn the final accuracy mark.
6. Questions saying "give reasons" require the approved geometric wording — "angles in the same \
segment are equal", "alternate angles are equal", "opposite angles in a cyclic quadrilateral sum \
to 180 degrees". Informal paraphrase does not earn the reasoning mark. Vector proofs need the \
path expressed in vector terms rather than bare algebra.
7. Plotting: points are within half a small square of their true position, and cumulative \
frequency is plotted at the upper class boundary, never the midpoint.
8. Comparing two distributions requires both a measure of average and a measure of spread, and \
both interpreted in context. Quoting the two medians is a description; saying which group scored \
higher on average, and why, is the comparison.
9. Crossed-out work is marked only when nothing has replaced it. Where the candidate has crossed \
out an attempt and written another, mark the replacement."""


SUBJECT_GUIDELINES: dict[tuple[str, str], str] = {
    (BOARD_CAMBRIDGE, "5070"): CAMBRIDGE_5070_CHEMISTRY,
    (BOARD_CAMBRIDGE, "5090"): CAMBRIDGE_5090_BIOLOGY,
    (BOARD_EDEXCEL, "4CH1"): EDEXCEL_4CH1_CHEMISTRY,
    (BOARD_EDEXCEL, "4BI1"): EDEXCEL_4BI1_BIOLOGY,
    (BOARD_EDEXCEL, "4MA1"): EDEXCEL_4MA1_MATHS,
}


# --------------------------------------------------------------------------
# Layer 5 — paper
#
# Keyed (board key, `Subject.code`, `PastPaper.paper_number`) — e.g.
# ("cambridge", "5070", "Paper 2"). Resolves for past papers only: homework and
# classifieds carry no paper number, so the layer is simply omitted there.
#
# Empty pending the tutor's paper-level guidance. Paper numbers are free text a
# tutor typed at upload, so lookup normalises whitespace and case.
# --------------------------------------------------------------------------

PAPER_GUIDELINES: dict[tuple[str, str, str], str] = {}


def _paper_key(paper_number: str) -> str:
    """Past paper numbers are tutor-typed free text — "Paper 2", "paper 2",
    " Paper  2 " are the same paper."""
    return " ".join(paper_number.split()).casefold()


def build_marking_guidelines(
    exam_board: str, subject_code: str, paper_number: str | None = None
) -> str:
    """The marking guidance block for this board, subject and (optional) paper.

    General to specific, so a narrower layer reads as refining the one above
    it. Returns "" when the board cannot be identified, so callers can skip an
    empty block the same way they do for the tutor Knowledge Base.
    """
    board = normalize_board(exam_board)
    if board is None:
        return ""
    principles = BOARD_PRINCIPLES.get(board)
    if principles is None:
        return ""

    parts = [
        "Exam board marking guidance for this paper, general to specific. The official mark "
        "scheme for this paper outranks everything here — where the scheme is specific about a "
        "mark, the scheme decides it. The board-level sections below (its marking principles, "
        "and its command word definitions where given) are that board's published standard. "
        "The subject and paper sections are guidance supplied by the tutor for cases the scheme "
        "leaves open; follow them, but if one of them would change a mark the official scheme "
        "has already settled, follow the scheme and set confidence 'low' so the tutor sees the "
        "conflict.",
        principles,
        MARK_SCHEME_CONVENTIONS,
        ZERO_RULE,
    ]

    command_words = COMMAND_WORDS.get(board)
    if command_words:
        parts.append(command_words)

    family = SUBJECT_FAMILY.get((board, subject_code))
    if family:
        family_block = FAMILY_GUIDELINES.get((board, family))
        if family_block:
            parts.append(family_block)

    subject = SUBJECT_GUIDELINES.get((board, subject_code))
    if subject:
        parts.append(subject)

    if paper_number:
        paper = PAPER_GUIDELINES.get((board, subject_code, _paper_key(paper_number)))
        if paper:
            parts.append(paper)

    return "\n\n".join(parts)
