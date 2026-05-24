import { useRef } from 'react'
import { useDropzone } from 'react-dropzone'
import { UploadCloud, ImagePlus, FolderPlus, Video } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { isImageFile, isVideoFile, IMAGE_EXTS, VIDEO_EXTS } from '../lib/api'

/**
 * Multi-mode dropzone:
 *   • Accepts images, videos, AND folder-of-files (drag & drop or "Folder" button).
 *   • Recursively walks dropped directories using the WebKit entry API.
 *   • Surfaces a "Folder" picker via a sibling <input webkitdirectory>.
 *
 * Why the buttons live OUTSIDE the dropzone root:
 *   react-dropzone attaches a click handler to the root div that opens the
 *   native file picker. Even with stopPropagation, programmatically clicking
 *   a hidden <input> that lives inside that root will bubble up and trigger
 *   the file picker BEFORE the folder picker. Keeping the inputs as siblings
 *   completely sidesteps the issue.
 */
export default function ImageDropzone({
  onFiles,
  multiple = true,
  compact = false,
  acceptVideo = true,
  hint = 'Drop photos, ROV videos, or an entire dive-day folder',
}) {
  const folderInputRef = useRef(null)

  const accept = acceptVideo
    ? { 'image/*': IMAGE_EXTS, 'video/*': VIDEO_EXTS }
    : { 'image/*': IMAGE_EXTS }

  const filterFiles = (files) =>
    files.filter((f) => isImageFile(f) || (acceptVideo && isVideoFile(f)))

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop: (accepted) => {
      const files = filterFiles(accepted)
      if (files.length) {
        onFiles(files)
      } else if (accepted.length) {
        toast.error('Dropped files are not supported images or videos')
      }
    },
    accept,
    multiple,
    maxSize: 500 * 1024 * 1024,
    useFsAccessApi: false,
    noClick: true,          // we drive the picker ourselves via the button below
    noKeyboard: true,
  })

  const onFolderChange = (e) => {
    const files = Array.from(e.target.files || [])
    const filtered = filterFiles(files)
    if (!filtered.length) {
      toast.error(
        files.length
          ? 'No JPG/PNG/WEBP images or supported videos in that folder'
          : 'Folder is empty or could not be read — try Browse Files instead',
      )
    } else {
      toast.success(`Added ${filtered.length} file${filtered.length === 1 ? '' : 's'} from folder`)
      onFiles(filtered)
    }
    e.target.value = ''
  }

  return (
    <div>
      <div
        {...getRootProps()}
        onClick={open}    // single-click anywhere opens the file picker
        className={clsx(
          'group relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed transition-all',
          isDragActive
            ? 'border-brand-400 bg-brand-400/10 shadow-glow'
            : 'border-white/15 bg-white/[0.02] hover:border-brand-400/60 hover:bg-white/[0.04]',
          compact ? 'p-4' : 'p-8',
        )}
      >
        <input {...getInputProps()} />

        {/* Bubble flair */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden opacity-30">
          {[...Array(6)].map((_, i) => (
            <span
              key={i}
              className="absolute bottom-0 block rounded-full bg-brand-300/40 animate-bubble"
              style={{
                left: `${10 + i * 15}%`,
                width: `${6 + (i % 3) * 4}px`,
                height: `${6 + (i % 3) * 4}px`,
                animationDelay: `${i * 0.7}s`,
                animationDuration: `${5 + (i % 3)}s`,
              }}
            />
          ))}
        </div>

        <div className="relative flex flex-col items-center text-center">
          <div className="rounded-2xl bg-gradient-to-br from-brand-400/20 to-accent-500/10 p-3 ring-1 ring-brand-400/30">
            {compact ? <ImagePlus size={20} className="text-brand-300" /> : <UploadCloud size={28} className="text-brand-300" />}
          </div>

          {!compact && (
            <h3 className="mt-3 font-display text-base font-semibold text-white">
              Drop photos, videos, or a folder
            </h3>
          )}
          <p className={clsx('mt-1 text-xs text-slate-400', compact && 'text-[11px]')}>
            {compact ? 'Click or drop image / video' : (isDragActive ? 'Release to add' : hint)}
          </p>

          {!compact && (
            <div className="mt-3 text-[10px] uppercase tracking-wider text-slate-500">
              Images: JPG / PNG / WEBP{acceptVideo ? ' · Videos: MP4 / MOV / MKV / WEBM' : ''}
            </div>
          )}
        </div>
      </div>

      {/* Action buttons OUTSIDE the dropzone — keeps the folder click isolated */}
      {!compact && (
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          <button type="button" onClick={open} className="btn-outline text-xs">
            <ImagePlus size={14} /> Browse Files
          </button>
          <button type="button"
                  onClick={() => folderInputRef.current?.click()}
                  className="btn-ghost text-xs">
            <FolderPlus size={14} /> Add Folder
          </button>
          {acceptVideo && (
            <span className="pill-mute text-[10px]"><Video size={11} /> Videos OK</span>
          )}
        </div>
      )}

      {/* Hidden folder picker — sibling, NOT a child of the dropzone */}
      <input
        ref={folderInputRef}
        type="file"
        multiple
        webkitdirectory=""
        directory=""
        className="hidden"
        onChange={onFolderChange}
      />
    </div>
  )
}
