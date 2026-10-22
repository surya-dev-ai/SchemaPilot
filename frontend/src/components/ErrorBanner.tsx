type Props = {
  title?: string;
  message: string;
};

export function ErrorBanner({ title = "Request failed", message }: Props) {
  return (
    <p className="banner banner-error" role="alert">
      <strong>{title}</strong> {message}
    </p>
  );
}
