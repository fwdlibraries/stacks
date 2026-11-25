import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert, Badge, Button, Spinner } from 'react-bootstrap'
import { ListPlus, PencilSimple, Plus, Trash } from '@phosphor-icons/react'
import {
  useApplyOrder,
  useCreateCitation,
  useCreateSection,
  useDeleteCitation,
  useDeleteSection,
  useReadingListFull,
  useSetPublished,
  useUpdateCitation,
  useUpdateList,
  useUpdateSection,
  useUnlinkCitation,
  type Citation,
  type ListSection,
} from '@/api/hooks/useLists'
import { useCreateFromSource } from '@/api/hooks/useIngest'
import { useListClicks } from '@/api/hooks/useLinks'
import { apiErrorMessage } from '@/lib/apiError'
import { needsAttention } from '@/lib/sourceStatus'
import { CitationCard } from '@/components/citations/CitationCard'
import { CitationFormModal } from '@/components/citations/CitationFormModal'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { EmptyState } from '@/components/common/EmptyState'
import { ListDetailsModal } from '@/components/lists/ListDetailsModal'
import { BulkImportModal } from '@/components/lists/BulkImportModal'
import { SectionFormModal } from '@/components/lists/SectionFormModal'
import { ListDnd, SectionCitations, SortableCitation, SortableSection } from '@/components/lists/SortableList'

type Dialog =
  | { kind: 'details' }
  | { kind: 'section'; section?: ListSection }
  | { kind: 'deleteSection'; section: ListSection }
  | { kind: 'citation'; section: ListSection; citation?: Citation }
  | { kind: 'deleteCitation'; citation: Citation }
  | { kind: 'import' }
  | null

const VISIBILITY_LABELS = { public: 'Public', unlisted: 'Unlisted', institution: 'Organization only' }

/**
 * Reading list editor. Sections and citations reorder by drag-and-drop (or the
 * keyboard via their handles). Live collaboration (lib/websocket.ts) will build on this.
 */
export default function ListEditorView() {
  const { listId = '' } = useParams<{ listId: string }>()
  const { data: list, isLoading, isError } = useReadingListFull(listId)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const clicks = useListClicks(listId)

  const setPublished = useSetPublished(listId)
  const applyOrder = useApplyOrder(listId)
  const updateList = useUpdateList(listId)
  const createSection = useCreateSection(listId)
  const updateSection = useUpdateSection()
  const deleteSection = useDeleteSection()
  const createCitation = useCreateCitation()
  const updateCitation = useUpdateCitation()
  const deleteCitation = useDeleteCitation()
  const createFromSource = useCreateFromSource()
  const unlinkCitation = useUnlinkCitation()

  const mutations = [
    updateList,
    createSection,
    updateSection,
    deleteSection,
    createCitation,
    updateCitation,
    deleteCitation,
    createFromSource,
    unlinkCitation,
  ]
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

  const canEdit = Boolean(list.can_edit)
  const canPublish = Boolean(list.can_publish)
  const flagged = list.sections.reduce((n, s) => n + s.citations.filter((c) => c.is_bound && needsAttention(c)).length, 0)

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
          {canEdit && (
            <Button variant="outline-secondary" onClick={() => open({ kind: 'details' })}>
              Edit details
            </Button>
          )}
          {canEdit && list.sections.length > 0 && (
            <Button variant="outline-secondary" onClick={() => open({ kind: 'import' })}>
              Import
            </Button>
          )}
          {canPublish && (
            <Button
              variant={list.is_published ? 'outline-primary' : 'primary'}
              disabled={setPublished.isPending}
              onClick={() => setPublished.mutate(!list.is_published)}
            >
              {list.is_published ? 'Unpublish' : 'Publish'}
            </Button>
          )}
        </div>
      </header>

      {!canEdit && (
        <Alert variant="info" className="mt-3 mb-0">
          You can view this reading list but not change it.
        </Alert>
      )}

      {notice && (
        <Alert variant="success" className="mt-3 mb-0" dismissible onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}

      {flagged > 0 && (
        <Alert variant="warning" className="mt-3 mb-0">
          {flagged === 1
            ? '1 citation needs attention: its library record was removed or hidden in the catalogue. Replace it, or open it and unlink it to keep the current details.'
            : `${flagged} citations need attention: their library records were removed or hidden in the catalogue. Replace them, or open each one and unlink it to keep the current details.`}
        </Alert>
      )}
      {applyOrder.isError && (
        <Alert variant="danger" className="small mt-3" dismissible onClose={() => applyOrder.reset()}>
          {apiErrorMessage(applyOrder.error, 'The new order could not be saved, so it was undone.')}
        </Alert>
      )}
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
            canEdit ? (
              <Button variant="primary" onClick={() => open({ kind: 'section' })}>
                Add section
              </Button>
            ) : undefined
          }
        >
          {canEdit ? 'Add a section such as “Required” or “Week 1”, then add citations to it.' : 'This list is empty.'}
        </EmptyState>
      )}

      <ListDnd list={list} onReorder={(plan) => applyOrder.mutate(plan)}>
        {list.sections.map((section) => (
          <SortableSection key={section.id} section={section}>
            {(handle) => (
              <section className="mb-5" aria-labelledby={`section-${section.id}`}>
                <div className="d-flex align-items-start justify-content-between gap-2 mb-2">
                  <div className="d-flex align-items-start gap-1">
                    {canEdit && <div className="ms-n2">{handle}</div>}
                    <div>
                      <h2 id={`section-${section.id}`} className="h3 mb-1">
                        {section.title}
                      </h2>
                      {section.description && (
                        <p className="text-body-secondary small mb-0">{section.description}</p>
                      )}
                    </div>
                  </div>
                  <div className={canEdit ? 'd-flex gap-1 flex-shrink-0' : 'd-none'}>
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

                <SectionCitations section={section}>
                  {section.citations.length === 0 && (
                    <p className="text-body-secondary small mb-2">
                      {canEdit ? 'No citations in this section. Add one, or drag one here.' : 'No citations in this section.'}
                    </p>
                  )}
                  {section.citations.map((citation) => (
                    <SortableCitation key={citation.id} citation={citation} sectionId={section.id}>
                      {(citationHandle, isDragging) => (
                        <CitationCard
                          citation={citation}
                          showStaffNote
                          linkPreview
                          clicks={list.is_published ? (clicks.data?.[citation.id] ?? { total: 0, last_30_days: 0 }) : undefined}
                          isDragging={isDragging}
                          dragHandle={canEdit ? citationHandle : undefined}
                          onEdit={canEdit ? (c) => open({ kind: 'citation', section, citation: c }) : undefined}
                          onDelete={canEdit ? () => open({ kind: 'deleteCitation', citation }) : undefined}
                        />
                      )}
                    </SortableCitation>
                  ))}
                </SectionCitations>

                {canEdit && (
                  <Button
                    variant="outline-primary"
                    size="sm"
                    className="d-inline-flex align-items-center gap-1 mt-1"
                    onClick={() => open({ kind: 'citation', section })}
                  >
                    <Plus aria-hidden="true" /> Add citation
                  </Button>
                )}
              </section>
            )}
          </SortableSection>
        ))}
      </ListDnd>

      {canEdit && list.sections.length > 0 && (
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
          canChangeVisibility={canPublish}
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

      {dialog?.kind === 'import' && (
        <BulkImportModal
          listId={listId}
          sections={list.sections}
          onCancel={close}
          onDone={(summary) => {
            setNotice(summary)
            close()
          }}
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
          onAddFromSource={(candidate, input) =>
            createFromSource.mutate(
              {
                sectionId: dialog.section.id,
                source_system: candidate.source_system,
                source_identifier: candidate.source_identifier,
                ...input,
              },
              { onSuccess: close }
            )
          }
          isAddingFromSource={createFromSource.isPending}
          addFromSourceError={errorOf(createFromSource, 'That record could not be added.')}
          onUnlink={dialog.citation ? () => unlinkCitation.mutateAsync(dialog.citation!.id) : undefined}
          unlinkError={errorOf(unlinkCitation, 'The citation could not be unlinked.')}
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
