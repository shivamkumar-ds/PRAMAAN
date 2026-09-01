// Static, documented category list for the Upload Tender form -- same
// category of decision as recommendationLabels.ts / roleDescriptions.ts:
// a fixed, presentation-layer list, not a backend enum, so it can grow
// without a migration. The backend stores whatever string is selected
// here as free text (Tender.category), so this list IS the source of
// truth for what "a category" means today.
//
// Sourced from the industries PRAMAAN already claims to serve on the
// marketing site (landingData.ts's solutionVerticals/industries), kept
// as a single flat list here rather than duplicated across both files.
export const TENDER_CATEGORIES: string[] = [
  "Construction & Infrastructure",
  "Manufacturing",
  "IT & Technology Services",
  "Healthcare",
  "Oil, Gas & Energy",
  "Defence & Aerospace",
  "Government & Public Sector",
  "Telecom",
  "Consulting & Professional Services",
  "Enterprise Procurement",
  "Other",
];
