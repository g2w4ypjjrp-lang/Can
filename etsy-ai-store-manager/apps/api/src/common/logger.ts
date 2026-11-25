import { LoggerService } from '@nestjs/common';
import { pino, type Logger } from 'pino';

export function createRootLogger(level: string): Logger {
  return pino({
    level,
    base: { service: 'api' },
    redact: {
      paths: [
        'req.headers.authorization',
        'req.headers.cookie',
        '*.access_token',
        '*.refresh_token',
        '*.password',
        '*.token',
      ],
      censor: '[REDACTED]',
    },
  });
}

/** Adapter so Nest's internal logs go through pino as structured JSON. */
export class PinoNestLogger implements LoggerService {
  constructor(private readonly logger: Logger) {}
  log(message: unknown, context?: string) {
    this.logger.info({ context }, String(message));
  }
  error(message: unknown, trace?: string, context?: string) {
    this.logger.error({ context, trace }, String(message));
  }
  warn(message: unknown, context?: string) {
    this.logger.warn({ context }, String(message));
  }
  debug(message: unknown, context?: string) {
    this.logger.debug({ context }, String(message));
  }
  verbose(message: unknown, context?: string) {
    this.logger.trace({ context }, String(message));
  }
}
