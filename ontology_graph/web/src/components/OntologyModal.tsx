import { useEffect, useRef, useState } from "react";
import type { OntologyGraph as Graph } from "../types";
import OntologyGraph from "./OntologyGraph";

interface Props {
  open: boolean;
  onClose: () => void;
  graph: Graph | null;
}

// Native <dialog>: focus is trapped, Esc closes it, and the page behind is inert while it is open.
export default function OntologyModal({ open, onClose, graph }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      setShown(true); // draw the graph only once the dialog has a size, so it fits the view
    }
    if (!open && dialog.open) dialog.close();
    if (!open) setShown(false);
  }, [open]);

  return (
    <dialog ref={ref} className="ont-dialog" aria-label="Plan ontology" onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <div className="dialog-head">
        <h2>Plan ontology</h2>
        <button className="secondary" onClick={onClose}>Close</button>
      </div>
      {shown && <OntologyGraph graph={graph} />}
    </dialog>
  );
}
