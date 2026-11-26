import { forwardRef, type ComponentPropsWithoutRef } from 'react';

type ButtonProps = ComponentPropsWithoutRef<'button'> & {
  variant?: 'primary' | 'secondary' | 'ghost';
  tone?: 'default' | 'danger';
  size?: 'normal' | 'large';
  busy?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    tone = 'default',
    size = 'normal',
    busy = false,
    disabled,
    type = 'button',
    className = '',
    children,
    ...props
  },
  ref,
) {
  return (
    <button
      {...props}
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      data-tone={tone}
      className={`fb-button fb-button--${variant}${size === 'large' ? ' fb-button--large' : ''} ${className}`.trim()}
    >
      {busy && <span className="button-spinner" aria-hidden="true" />}
      {children}
    </button>
  );
});
