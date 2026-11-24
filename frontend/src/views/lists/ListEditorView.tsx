import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert, Badge, Button, Spinner } from 'react-bootstrap'
import { ListPlus, PencilSimple, Plus, Trash } from '@phosphor-icons/react'
import {
  useCreateCitation,
  useCreateSection,
  useDeleteCitation,
  useDeleteSection,
  useReadingListFull,
  useSetPublished,
  useUpdateCitation,
  useUpdateList,
  useUpdateSection,
  type Citation,
  type ListSection,
} from '@/api/hooks/useLists'
import { apiErrorMessage } from '@/lib/apiError'
import { CitationCard } from '@/components/citations/CitationCard'
import { CitationFormModal } from '@/components/citations/CitationFormModal'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { EmptyState } from '@/components/common/EmptyState'
import { ListDetailsModal } from '@/components/lists/ListDetailsModal'
import { SectionFormModal } from '@/components/lists/SectionFormModal'

type Dialog =
  | { kind: 'details' }
  | { kind: 'section'; section?: ListSection }
  | { kind: 'deleteSection'; section: ListSection }
  | { kind: 'citation'; section: ListSection; citation?: Citation }
  | { kind: 'deleteCitation'; citation: Citation }
  | null

const VISIBILITY_LABELS = { public: 'Public', unlisted: 'Unlisted', institution: 'Organization only' }

/**
 * Reading list editor. Drag-and-drop reordering (dnd-kit) and live collaboration
 * (lib/websocket.ts) will build on this view.
 */
export default function ListEditorView() {
  const { listId = '' } = useParams<{ listId: string }>()
  const { data: list, isLoading, isError } = useReadingListFull(listId)
  const [dialog, setDialog] = useState<Dialog>(null)

  const setPublished = useSetPublished(listId)
  const updateList = useUpdateList(listId)
  const createSection = useCreateSection(listId)
  const updateSection = useUpdateSection()
  const deleteSection = useDeleteSection()
  const createCitation = useCreateCitation()
  const updateCitation = useUpdateCitation()
  const deleteCitation = useDeleteCitation()

  const mutations = [updateList, createSection, updateSection, deleteSection, createCitation, updateCitation, deleteCitation]
  const open = (next: Dialog) => {
    mutations.forEach((m) => m.reset()) // don't show a previous dialog's error
    setDialog(next)
  }
  const close = () => setDialog(null)
  const errorOf = (m: { error: unknown }, fallback: string) => (m.error ? apiErrorMessage(m.error, fallback) : null)

  if (isLoading) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading reading list…</span>
        </Spinner>
      </div>
    )
  }

  if (isError || !list) {
    return (
      <Alert variant="warning">
        This reading list could not be loaded. <Link to="/lists">Back to reading lists</Link>
      </Alert>
    )
  }

  return (
    <div style={{ maxWidth: '800px' }}>
      <nav aria-label="breadcrumb" className="small mb-2">
        <Link to="/lists">Reading lists</Link>
      </nav>

      <header className="d-flex flex-wrap align-items-start justify-content-between gap-3">
        <div>
          <div className="d-flex align-items-center gap-2 mb-1">
            <h1 className="mb-0">{list.title}</h1>
            <Badge bg={list.is_published ? 'published' : 'secondary'}>
              {list.is_published ? 'Published' : 'Draft'}
            </Badge>
          </div>
          {list.description && <p className="text-body-secondary mb-1">{list.description}</p>}
          <p className="small text-body-secondary mb-0">Visibility: {VISIBILITY_LABELS[list.visibility]}</p>
        </div>
        <div className="d-flex gap-2">
          <Button variant="outline-secondary" onClick={() => open({ kind: 'details' })}>
            Edit details
          </Button>
          <Button
            variant={list.is_published ? 'outline-primary' : 'primary'}
            disabled={setPublished.isPending}
            onClick={() => setPublished.mutate(!list.is_published)}
          >
            {list.is_published ? 'Unpublish' : 'Publish'}
          </Button>
        </div>
      </header>
      {setPublished.isError && (
        <Alert variant="danger" className="small mt-3">
          {apiErrorMessage(setPublished.error, 'The reading list could not be updated. Try again.')}
        </Alert>
      )}

      <hr className="my-4" />

      {list.sections.length === 0 && (
        <EmptyState
          icon={ListPlus}
          heading="No sections yet"
          action={
            <Button variant="primary" onClick={() => open({ kind: 'section' })}>
              Add section
            </Button>
          }
        >
          Add a section such as “Required” or “Week 1”, then add citations to it.
        </EmptyState>
      )}

      {list.sections.map((section) => (
        <section key={section.id} className="mb-5" aria-labelledby={`section-${section.id}`}>
          <div className="d-flex align-items-start justify-content-between gap-2 mb-2">
            <div>
              <h2 id={`section-${section.id}`} className="h3 mb-1">
                {section.title}
              </h2>
              {section.description && <p className="text-body-secondary small mb-0">{section.description}</p>}
            </div>
            <div className="d-flex gap-1 flex-shrink-0">
              <Button
                variant="link"
                size="sm"
                className="text-body-secondary"
                onClick={() => open({ kind: 'section', section })}
                aria-label={`Edit section ${section.title}`}
              >
                <PencilSimple aria-hidden="true" /> Edit
              </Button>
              {section.citations.length === 0 && (
                <Button
                  variant="link"
                  size="sm"
                  className="text-danger"
                  onClick={() => open({ kind: 'deleteSection', section })}
                  aria-label={`Delete section ${section.title}`}
                >
                  <Trash aria-hidden="true" /> Delete
                </Button>
              )}
            </div>
          </div>

          {section.citations.length === 0 && (
            <p className="text-body-secondary small">No citations in this section.</p>
          )}
          {section.citations.map((citation) => (
            <CitationCard
              key={citation.id}
              citation={citation}
              showStaffNote
              onEdit={(c) => open({ kind: 'citation', section, citation: c })}
              onDelete={() => open({ kind: 'deleteCitation', citation })}
            />
          ))}

          <Button
            variant="outline-primary"
            size="sm"
            className="d-inline-flex align-items-center gap-1 mt-1"
            onClick={() => open({ kind: 'citation', section })}
          >
            <Plus aria-hidden="true" /> Add citation
          </Button>
        </section>
      ))}

      {list.sections.length > 0 && (
        <Button
          variant="outline-secondary"
          className="d-inline-flex align-items-center gap-1"
          onClick={() => open({ kind: 'section' })}
        >
          <ListPlus aria-hidden="true" /> Add section
        </Button>
      )}

      {/* ── Dialogs ───────────────────────────────────────────────────────── */}

      {dialog?.kind === 'details' && (
        <ListDetailsModal
          list={list}
          isPending={updateList.isPending}
          error={errorOf(updateList, 'The details could not be saved.')}
          onSubmit={(input) => updateList.mutate(input, { onSuccess: close })}
          onCancel={close}
        />
      )}

      {dialog?.kind === 'section' && (
        <SectionFormModal
          key={dialog.section?.id ?? 'new'}
          section={dialog.section}
          isPending={createSection.isPending || updateSection.isPending}
          error={
            dialog.section
              ? errorOf(updateSection, 'The section could not be saved.')
              : errorOf(createSection, 'The section could not be added.')
          }
          onSubmit={(input) =>
            dialog.section
              ? updateSection.mutate({ id: dialog.section.id, ...input }, { onSuccess: close })
              : createSection.mutate(input, { onSuccess: close })
          }
          onCancel={close}
        />
      )}

      {dialog?.kind === 'citation' && (
        <CitationFormModal
          key={dialog.citation?.id ?? `new-${dialog.section.id}`}
          citation={dialog.citation}
          sectionTitle={dialog.section.title}
          isPending={createCitation.isPending || updateCitation.isPending}
          error={
            dialog.citation
              ? errorOf(updateCitation, 'The citation could not be saved.')
              : errorOf(createCitation, 'The citation could not be added.')
          }
          onSubmit={(input) =>
            dialog.citation
              ? updateCitation.mutate({ id: dialog.citation.id, ...input }, { onSuccess: close })
              : createCitation.mutate({ sectionId: dialog.section.id, ...input }, { onSuccess: close })
          }
          onCancel={close}
        />
      )}

      <ConfirmModal
        show={dialog?.kind === 'deleteSection'}
        title="Delete section"
        confirmLabel="Delete section"
        isPending={deleteSection.isPending}
        error={errorOf(deleteSection, 'The section could not be deleted.')}
        onConfirm={() =>
          dialog?.kind === 'deleteSection' && deleteSection.mutate(dialog.section.id, { onSuccess: close })
        }
        onCancel={close}
      >
        Delete the section “{dialog?.kind === 'deleteSection' ? dialog.section.title : ''}”? This cannot be undone.
      </ConfirmModal>

      <ConfirmModal
        show={dialog?.kind === 'deleteCitation'}
        title="Delete citation"
        confirmLabel="Delete citation"
        isPending={deleteCitation.isPending}
        error={errorOf(deleteCitation, 'The citation could not be deleted.')}
        onConfirm={() =>
          dialog?.kind === 'deleteCitation' && deleteCitation.mutate(dialog.citation.id, { onSuccess: close })
        }
        onCancel={close}
      >
        Delete “{dialog?.kind === 'deleteCitation' ? dialog.citation.title : ''}” from this reading list? This
        cannot be undone.
      </ConfirmModal>
    </div>
  )
}
