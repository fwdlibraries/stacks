/**
 * Drag-and-drop for the list editor (dnd-kit). Sections reorder by their handle;
 * citations reorder within a section or move to another one. Keyboard: focus a
 * handle, Space to pick up, arrow keys to move, Space to drop, Escape to cancel.
 */
import { forwardRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  pointerWithin,
  useDroppable,
  useSensor,
  useSensors,
  type Announcements,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
  type UniqueIdentifier,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { DotsSixVertical } from '@phosphor-icons/react'
import type { Citation, ListSection, ReadingList } from '@/api/hooks/useLists'
import { planCitationDrop, planSectionMove, type OrderPlan } from '@/lib/listOrder'

// ── Draggable ids and data ───────────────────────────────────────────────────

type DragData =
  | { type: 'section'; sectionId: string; title: string }
  | { type: 'citation'; sectionId: string; citationId: string; title: string }
  | { type: 'section-drop'; sectionId: string; title: string }

const sectionDragId = (id: string) => `section:${id}`
const citationDragId = (id: string) => `citation:${id}`
const sectionDropId = (id: string) => `section-drop:${id}`

const dataOf = (item: { data: { current?: unknown } } | null | undefined) =>
  item?.data.current as DragData | undefined

/**
 * Sections only collide with sections. Citations prefer the citation under the
 * pointer, then the section area under it (so empty sections accept drops), and
 * fall back to the closest candidate (used by the keyboard sensor).
 */
const collisionDetection: CollisionDetection = (args) => {
  const activeType = dataOf(args.active)?.type
  const candidates = args.droppableContainers.filter((container) => {
    const type = dataOf(container)?.type
    return activeType === 'section' ? type === 'section' : type === 'citation' || type === 'section-drop'
  })
  const scoped = { ...args, droppableContainers: candidates }
  if (activeType !== 'section') {
    const under = pointerWithin(scoped)
    const citation = under.find((c) => String(c.id).startsWith('citation:'))
    if (citation) return [citation]
    if (under.length) return under
  }
  return closestCenter(scoped)
}

// ── Provider ─────────────────────────────────────────────────────────────────

interface ListDndProps {
  list: ReadingList
  onReorder: (plan: OrderPlan) => void
  children: ReactNode
}

export function ListDnd({ list, onReorder, children }: ListDndProps) {
  const [active, setActive] = useState<DragData | null>(null)
  const sensors = useSensors(
    // A small distance threshold keeps clicks on the handle from starting a drag
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const handleDragStart = ({ active }: DragStartEvent) => setActive(dataOf(active) ?? null)

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    setActive(null)
    const from = dataOf(active)
    const to = dataOf(over)
    if (!from || !to) return

    let plan: OrderPlan | null = null
    if (from.type === 'section' && to.type === 'section') {
      plan = planSectionMove(list, from.sectionId, to.sectionId)
    } else if (from.type === 'citation' && (to.type === 'citation' || to.type === 'section-drop')) {
      plan = planCitationDrop(list, from.citationId, {
        sectionId: to.sectionId,
        citationId: to.type === 'citation' ? to.citationId : undefined,
      })
    }
    if (plan) onReorder(plan)
  }

  const activeCitation =
    active?.type === 'citation'
      ? list.sections.flatMap((s) => s.citations).find((c) => c.id === active.citationId)
      : undefined

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setActive(null)}
      accessibility={{ announcements: announcements(list), screenReaderInstructions }}
    >
      <SortableContext items={list.sections.map((s) => sectionDragId(s.id))} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
      <DragOverlay>
        {active && (
          <div className="card shadow p-3 bg-white" style={{ cursor: 'grabbing' }}>
            <span className="text-caps text-body-secondary d-block mb-1">
              {active.type === 'section' ? 'Section' : 'Citation'}
            </span>
            <strong>{active.title}</strong>
            {activeCitation?.author?.length ? (
              <span className="d-block small text-body-secondary">{activeCitation.author.join(', ')}</span>
            ) : null}
          </div>
        )}
      </DragOverlay>
    </DndContext>
  )
}

// ── Sortable pieces ──────────────────────────────────────────────────────────

/** Drag handle button; drag listeners go on this element only */
export const DragHandle = forwardRef<
  HTMLButtonElement,
  { label: string } & ButtonHTMLAttributes<HTMLButtonElement>
>(function DragHandle({ label, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      className="btn btn-link btn-sm text-body-secondary p-1 lh-1"
      style={{ cursor: 'grab', touchAction: 'none' }}
      {...props}
      aria-label={label}
    >
      <DotsSixVertical size={20} weight="bold" aria-hidden="true" />
    </button>
  )
})

type HandleRender = (handle: ReactNode, isDragging: boolean) => ReactNode

export function SortableSection({ section, children }: { section: ListSection; children: HandleRender }) {
  const sortable = useSortable({
    id: sectionDragId(section.id),
    data: { type: 'section', sectionId: section.id, title: section.title } satisfies DragData,
  })
  const handle = (
    <DragHandle
      label={`Reorder section ${section.title}`}
      ref={sortable.setActivatorNodeRef}
      {...sortable.attributes}
      {...sortable.listeners}
    />
  )
  return (
    <div
      ref={sortable.setNodeRef}
      style={{
        transform: CSS.Translate.toString(sortable.transform),
        transition: sortable.transition,
        opacity: sortable.isDragging ? 0.4 : undefined,
      }}
    >
      {children(handle, sortable.isDragging)}
    </div>
  )
}

/** The citations area of a section: a sortable list plus a drop zone for moves */
export function SectionCitations({ section, children }: { section: ListSection; children: ReactNode }) {
  const { setNodeRef, isOver, active } = useDroppable({
    id: sectionDropId(section.id),
    data: { type: 'section-drop', sectionId: section.id, title: section.title } satisfies DragData,
  })
  const draggingCitation = dataOf(active)?.type === 'citation'
  return (
    <SortableContext items={section.citations.map((c) => citationDragId(c.id))} strategy={verticalListSortingStrategy}>
      <div
        ref={setNodeRef}
        className="rounded"
        style={{
          minHeight: draggingCitation ? '3.5rem' : undefined,
          outline: draggingCitation && isOver ? '2px dashed var(--bs-primary)' : undefined,
          outlineOffset: '4px',
        }}
      >
        {children}
      </div>
    </SortableContext>
  )
}

export function SortableCitation({
  citation,
  sectionId,
  children,
}: {
  citation: Citation
  sectionId: string
  children: HandleRender
}) {
  const sortable = useSortable({
    id: citationDragId(citation.id),
    data: { type: 'citation', sectionId, citationId: citation.id, title: citation.title } satisfies DragData,
  })
  const handle = (
    <DragHandle
      label={`Reorder ${citation.title}`}
      ref={sortable.setActivatorNodeRef}
      {...sortable.attributes}
      {...sortable.listeners}
    />
  )
  return (
    <div
      ref={sortable.setNodeRef}
      style={{ transform: CSS.Translate.toString(sortable.transform), transition: sortable.transition }}
    >
      {children(handle, sortable.isDragging)}
    </div>
  )
}

// ── Screen reader text ───────────────────────────────────────────────────────

const screenReaderInstructions = {
  draggable:
    'To reorder, press Space to pick up. Use the arrow keys to move, Space to drop, or Escape to cancel.',
}

function announcements(list: ReadingList): Announcements {
  const describe = (id: UniqueIdentifier | undefined) => {
    const [kind, rawId] = String(id ?? '').split(':')
    if (kind === 'section' || kind === 'section-drop') {
      const index = list.sections.findIndex((s) => s.id === rawId)
      return index === -1 ? '' : `section ${index + 1} of ${list.sections.length}, ${list.sections[index].title}`
    }
    for (const section of list.sections) {
      const index = section.citations.findIndex((c) => c.id === rawId)
      if (index !== -1) return `position ${index + 1} of ${section.citations.length} in ${section.title}`
    }
    return ''
  }
  const title = (data: unknown) => (data as DragData | undefined)?.title ?? 'item'

  return {
    onDragStart: ({ active }) => `Picked up ${title(active.data.current)}.`,
    onDragOver: ({ active, over }) =>
      over ? `${title(active.data.current)} is over ${describe(over.id)}.` : `${title(active.data.current)} is no longer over a drop area.`,
    onDragEnd: ({ active, over }) =>
      over ? `${title(active.data.current)} was dropped at ${describe(over.id)}.` : `${title(active.data.current)} was dropped.`,
    onDragCancel: ({ active }) => `Moving ${title(active.data.current)} was cancelled.`,
  }
}
