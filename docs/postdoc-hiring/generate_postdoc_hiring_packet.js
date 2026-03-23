const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  HeadingLevel,
  Packer,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
  LevelFormat,
} = require("/tmp/email-triage-docx-tools/node_modules/docx");

const root = "/Users/tianhao/Downloads/email-triage/docs/postdoc-hiring";
const out = path.join(root, "Postdoc_Hiring_Documentation_Packet.docx");

const border = { style: BorderStyle.SINGLE, size: 1, color: "CFCFCF" };
const cellBorders = { top: border, bottom: border, left: border, right: border };

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 120, ...(opts.spacing || {}) },
    alignment: opts.alignment,
    heading: opts.heading,
    style: opts.style,
    children: [new TextRun({ text, bold: !!opts.bold })],
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 80 },
    children: [new TextRun(text)],
  });
}

function numbered(text) {
  return new Paragraph({
    numbering: { reference: "numbers", level: 0 },
    spacing: { after: 80 },
    children: [new TextRun(text)],
  });
}

function cell(text, opts = {}) {
  return new TableCell({
    borders: cellBorders,
    width: { size: opts.width || 3120, type: WidthType.DXA },
    shading: opts.shading ? { fill: opts.shading, type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({
      spacing: { after: 60 },
      children: [new TextRun({ text, bold: !!opts.bold })],
    })],
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Title",
        name: "Title",
        basedOn: "Normal",
        run: { font: "Arial", size: 34, bold: true, color: "000000" },
        paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 120, after: 180 } },
      },
      {
        id: "Heading1",
        name: "Heading 1",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 28, bold: true, color: "000000" },
        paragraph: { spacing: { before: 220, after: 120 }, outlineLevel: 0 },
      },
      {
        id: "Heading2",
        name: "Heading 2",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 24, bold: true, color: "000000" },
        paragraph: { spacing: { before: 180, after: 100 }, outlineLevel: 1 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          {
            level: 0,
            format: LevelFormat.BULLET,
            text: "•",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } },
          },
        ],
      },
      {
        reference: "numbers",
        levels: [
          {
            level: 0,
            format: LevelFormat.DECIMAL,
            text: "%1.",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } },
          },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              children: [
                new TextRun("Page "),
                new TextRun({ children: [PageNumber.CURRENT] }),
                new TextRun(" of "),
                new TextRun({ children: [PageNumber.TOTAL_PAGES] }),
              ],
            }),
          ],
        }),
      },
      children: [
        p("Documentation Packet for Current Postdoctoral / Research Associate Recruitment", {
          heading: HeadingLevel.TITLE,
        }),
        p("Prepared for the current hiring cycle associated with Tianhao Wang's postdoctoral / research associate recruitment.", {
          alignment: AlignmentType.CENTER,
        }),

        p("1. Purpose", { heading: HeadingLevel.HEADING_1 }),
        p("This packet consolidates the core documentation needed to run the current search in a structured, fair, and well-documented way. It is designed to support the posting, screening, interviewing, and onboarding stages of the hire."),
        bullet("search scope and role goals"),
        bullet("search governance and fairness principles"),
        bullet("structured screening and interview documentation"),
        bullet("evaluation rubric and decision process"),
        bullet("mentoring and onboarding plan"),
        bullet("recordkeeping checklist"),

        p("2. Search Scope and Role Goals", { heading: HeadingLevel.HEADING_1 }),
        p("The position is intended for a postdoctoral-level research hire or research associate hire supporting Tianhao Wang's research program. The hire is expected to contribute to active research projects, help move prototypes and experimental systems forward, collaborate with current lab members, and support paper- and project-facing execution."),
        bullet("contribute research ideas and technical execution with limited day-to-day supervision"),
        bullet("implement, test, and refine research prototypes"),
        bullet("engage thoughtfully with privacy, security, and data systems style research questions"),
        bullet("collaborate effectively with the PI and other project participants"),
        bullet("communicate progress clearly in meetings, writing, and technical discussions"),

        p("3. Search Governance and Fairness Principles", { heading: HeadingLevel.HEADING_1 }),
        p("The search will be run using a structured, job-related, and consistently documented process."),
        bullet("candidates are evaluated against role-relevant criteria rather than informal impressions"),
        bullet("the same core interview topics are used across candidates"),
        bullet("notes are recorded in a way that can explain the basis of decisions"),
        bullet("conflicts of interest or prior close advising relationships are flagged and managed"),
        bullet("final decisions rely on overall fit, research readiness, communication, independence, and collaboration potential"),
        bullet("avoid off-the-cuff criteria that were not applied to other candidates"),

        p("4. Screening Process", { heading: HeadingLevel.HEADING_1 }),
        p("4.1 Initial file review", { heading: HeadingLevel.HEADING_2 }),
        bullet("research area alignment with the position"),
        bullet("evidence of technical depth"),
        bullet("publication or project track record"),
        bullet("independence and execution ability"),
        bullet("communication clarity in materials"),
        bullet("fit with the lab's current project needs"),
        p("4.2 Shortlisting", { heading: HeadingLevel.HEADING_2 }),
        bullet("strong research fit"),
        bullet("evidence the candidate can execute independently"),
        bullet("clear potential to contribute in the first few months"),
        bullet("no obvious mismatch with the position's technical direction"),
        p("4.3 Review notes", { heading: HeadingLevel.HEADING_2 }),
        bullet("one-line overall recommendation: advance / hold / decline"),
        bullet("2-4 concrete strengths"),
        bullet("1-3 concrete concerns or open questions"),
        bullet("whether concerns can be resolved in interview"),

        p("5. Structured Interview Plan", { heading: HeadingLevel.HEADING_1 }),
        p("All finalists should be asked substantially the same core questions, with follow-up only as needed to clarify research fit or logistics."),
        numbered("Please describe one recent project where you drove the technical work end to end. What was your contribution, what was difficult, and what would you change now?"),
        numbered("Tell us about a research problem you are excited to work on next and why you think it is important."),
        numbered("Describe a time when an experiment, prototype, or system did not behave as expected. How did you debug it?"),
        numbered("What kinds of collaboration structures help you do your best work?"),
        numbered("How do you balance research exploration with the need to ship a result on a deadline?"),
        numbered("If you joined this group, what would you want to accomplish in the first three months?"),
        p("Interview documentation expectations:", { heading: HeadingLevel.HEADING_2 }),
        bullet("date and participants"),
        bullet("the questions actually asked"),
        bullet("a short note under each evaluation dimension"),
        bullet("an overall recommendation with confidence level"),

        p("6. Evaluation Rubric", { heading: HeadingLevel.HEADING_1 }),
        new Table({
          columnWidths: [2400, 1800, 5160],
          margins: { top: 100, bottom: 100, left: 120, right: 120 },
          rows: [
            new TableRow({
              tableHeader: true,
              children: [
                cell("Dimension", { width: 2400, bold: true, shading: "DCE6F1" }),
                cell("Priority", { width: 1800, bold: true, shading: "DCE6F1" }),
                cell("What to look for", { width: 5160, bold: true, shading: "DCE6F1" }),
              ],
            }),
            new TableRow({
              children: [
                cell("Research fit", { width: 2400 }),
                cell("High", { width: 1800 }),
                cell("Alignment with current and near-term lab needs", { width: 5160 }),
              ],
            }),
            new TableRow({
              children: [
                cell("Technical depth and execution", { width: 2400 }),
                cell("High", { width: 1800 }),
                cell("Evidence of independent technical ownership and end-to-end delivery", { width: 5160 }),
              ],
            }),
            new TableRow({
              children: [
                cell("Research independence", { width: 2400 }),
                cell("High", { width: 1800 }),
                cell("Ability to define and drive next steps without heavy prompting", { width: 5160 }),
              ],
            }),
            new TableRow({
              children: [
                cell("Communication", { width: 2400 }),
                cell("Medium", { width: 1800 }),
                cell("Clear explanation of technical decisions, results, and tradeoffs", { width: 5160 }),
              ],
            }),
            new TableRow({
              children: [
                cell("Collaboration and professionalism", { width: 2400 }),
                cell("Medium", { width: 1800 }),
                cell("Likely to work smoothly with the group and external collaborators", { width: 5160 }),
              ],
            }),
            new TableRow({
              children: [
                cell("Near-term readiness", { width: 2400 }),
                cell("Medium", { width: 1800 }),
                cell("Can contribute quickly with realistic ramp-up", { width: 5160 }),
              ],
            }),
          ],
        }),
        p("Suggested decision labels: strong yes, yes, mixed / hold, no."),

        p("7. Mentoring and Onboarding Plan", { heading: HeadingLevel.HEADING_1 }),
        p("The existing mentoring plan can be reused and lightly tailored for this hire."),
        p("First month", { heading: HeadingLevel.HEADING_2 }),
        bullet("set project scope and immediate deliverables"),
        bullet("review relevant papers, codebases, and datasets"),
        bullet("establish weekly meeting cadence with the PI"),
        bullet("introduce the hire to current collaborators and lab workflows"),
        bullet("define a concrete first technical milestone"),
        p("First three months", { heading: HeadingLevel.HEADING_2 }),
        bullet("complete at least one clearly scoped research or prototype milestone"),
        bullet("participate in regular project meetings"),
        bullet("produce progress updates in a repeatable format"),
        bullet("identify one paper- or project-facing deliverable"),
        bullet("clarify authorship, collaboration, and communication expectations"),
        p("Ongoing mentoring structure", { heading: HeadingLevel.HEADING_2 }),
        bullet("weekly 1:1 with the PI"),
        bullet("regular written or slide-based progress updates"),
        bullet("ad hoc technical unblock sessions as needed"),
        bullet("feedback on writing, experiments, and research direction"),
        bullet("support for conference submissions, talks, and professional development when appropriate"),

        p("8. Recordkeeping Checklist", { heading: HeadingLevel.HEADING_1 }),
        bullet("posting or requisition information"),
        bullet("search checklist"),
        bullet("candidate screening notes"),
        bullet("interview schedule and participant list"),
        bullet("structured interview questions"),
        bullet("interview notes and rubric scores"),
        bullet("final recommendation summary"),
        bullet("mentoring/onboarding plan shared with HR if requested"),

        p("9. Immediate Package to Share", { heading: HeadingLevel.HEADING_1 }),
        numbered("this documentation packet"),
        numbered("the structured interview question set and rubric"),
        numbered("the mentoring and onboarding plan"),
        p("If HR wants a shorter compliance packet, Sections 3, 5, 6, and 7 can be shared as a slim version."),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(out, buffer);
  console.log(out);
});
