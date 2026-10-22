type Props = {
  label: string;
  confirmed: boolean;
  onChange: (value: boolean) => void;
  help: string;
};

export function ConfirmPanel({ label, confirmed, onChange, help }: Props) {
  const id = label.replace(/\s+/g, "-").toLowerCase();
  return (
    <div className="confirm-panel">
      <label htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={confirmed}
          onChange={(event) => onChange(event.target.checked)}
        />{" "}
        {label}
      </label>
      <p className="muted">{help}</p>
    </div>
  );
}
