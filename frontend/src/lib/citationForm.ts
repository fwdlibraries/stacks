import type { Citation, CitationInput, ResourceType } from '@/api/hooks/useLists'

/** Form state: every field is a string (or boolean) while editing */
export interface CitationFormValues {
  resource_type: ResourceType
  title: string
  authors: string // one per line, "Family, Given"
  year: string
  publisher: string
  edition: string
  volume: string
  issue: string
  pages: string
  isbn: string
  doi: string
  url: string
  is_required: boolean
  student_note: string
  staff_note: string
}

export type CitationFormErrors = Partial<Record<keyof CitationFormValues, string>>

export const RESOURCE_TYPE_OPTIONS: { value: ResourceType; label: string }[] = [
  { value: 'book', label: 'Book' },
  { value: 'book_chapter', label: 'Book chapter' },
  { value: 'journal_article', label: 'Journal article' },
  { value: 'ebook', label: 'eBook' },
  { value: 'av_media', label: 'AV / Media' },
  { value: 'website', label: 'Website' },
  { value: 'other', label: 'Other' },
]

/** Which optional field groups apply to each resource type */
export function fieldsFor(type: ResourceType) {
  return {
    journal: type === 'journal_article' || type === 'book_chapter',
    isbn: type === 'book' || type === 'book_chapter' || type === 'ebook',
    edition: type === 'book' || type === 'ebook',
  }
}

export function emptyCitationForm(): CitationFormValues {
  return {
    resource_type: 'book',
    title: '',
    authors: '',
    year: '',
    publisher: '',
    edition: '',
    volume: '',
    issue: '',
    pages: '',
    isbn: '',
    doi: '',
    url: '',
    is_required: true,
    student_note: '',
    staff_note: '',
  }
}

export function citationToForm(citation: Citation): CitationFormValues {
  const text = (value: string | number | null | undefined) => (value == null ? '' : String(value))
  return {
    resource_type: citation.resource_type,
    title: citation.title,
    authors: (citation.author ?? []).join('\n'),
    year: text(citation.year),
    publisher: text(citation.publisher),
    edition: text(citation.edition),
    volume: text(citation.volume),
    issue: text(citation.issue),
    pages: text(citation.pages),
    isbn: text(citation.isbn),
    doi: text(citation.doi),
    url: text(citation.url),
    is_required: citation.is_required,
    student_note: text(citation.student_note),
    staff_note: text(citation.staff_note),
  }
}

/** Client-side checks mirroring the API's validation, so most errors show before saving */
export function validateCitationForm(values: CitationFormValues): CitationFormErrors {
  const errors: CitationFormErrors = {}
  if (!values.title.trim()) errors.title = 'Enter a title.'
  const year = values.year.trim()
  if (year && !/^\d{4}$/.test(year)) errors.year = 'Enter a four-digit year.'
  const url = values.url.trim()
  if (url && !/^https?:\/\//i.test(url)) errors.url = 'The URL must start with http:// or https://.'
  const doi = values.doi.trim().replace(/^(https?:\/\/(dx\.)?doi\.org\/|doi:)/i, '')
  if (doi && !doi.startsWith('10.')) errors.doi = 'A DOI looks like 10.1234/example.'
  return errors
}

/**
 * Convert form values to the API payload. Fields that don't apply to the chosen
 * resource type are left out, so editing never overwrites data the form doesn't show.
 */
export function formToCitationInput(values: CitationFormValues): CitationInput {
  const show = fieldsFor(values.resource_type)
  const year = values.year.trim()
  const input: CitationInput = {
    resource_type: values.resource_type,
    title: values.title.trim(),
    author: values.authors
      .split('\n')
      .map((name) => name.trim())
      .filter(Boolean),
    year: year ? Number(year) : null,
    publisher: values.publisher,
    doi: values.doi,
    url: values.url,
    is_required: values.is_required,
    student_note: values.student_note,
    staff_note: values.staff_note,
  }
  if (show.journal) Object.assign(input, { volume: values.volume, issue: values.issue, pages: values.pages })
  if (show.isbn) input.isbn = values.isbn
  if (show.edition) input.edition = values.edition
  return input
}
