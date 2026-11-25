import { ArgumentsHost, Catch, ExceptionFilter, HttpException, HttpStatus } from '@nestjs/common';
import type { Request, Response } from 'express';
import type { Logger } from 'pino';
import type { ApiErrorBody } from '@esm/shared';

/** Uniform error body; never leaks internal errors / SQL to clients. */
@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  constructor(private readonly logger: Logger) {}

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const res = ctx.getResponse<Response>();
    const req = ctx.getRequest<Request & { id?: string }>();
    const requestId = req.id ? String(req.id) : undefined;

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let message = 'Beklenmeyen bir hata oluştu';
    let details: unknown;

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const body = exception.getResponse();
      if (typeof body === 'string') message = body;
      else if (body && typeof body === 'object') {
        const b = body as { message?: unknown; details?: unknown };
        if (typeof b.message === 'string') message = b.message;
        else if (Array.isArray(b.message)) message = b.message.join(', ');
        details = b.details;
      }
    } else if (isPgError(exception)) {
      // RLS / permission violations -> 403, constraint violations -> 409/400
      if (exception.code === '42501') {
        status = HttpStatus.FORBIDDEN;
        message = 'Bu işlem için yetkiniz yok';
      } else if (exception.code === '23505') {
        status = HttpStatus.CONFLICT;
        message = 'Kayıt zaten mevcut';
      } else if (
        exception.code === '23514' ||
        exception.code === '23503' ||
        exception.code === '22P02'
      ) {
        status = HttpStatus.BAD_REQUEST;
        message = 'Geçersiz veri';
      }
    }

    if (status >= 500) {
      this.logger.error({ err: exception, requestId, path: req.url }, 'unhandled error');
    }

    const body: ApiErrorBody = {
      statusCode: status,
      error: HttpStatus[status] ?? 'Error',
      message,
      ...(details !== undefined ? { details } : {}),
      ...(requestId ? { requestId } : {}),
    };
    res.status(status).json(body);
  }
}

function isPgError(e: unknown): e is { code: string } {
  return (
    typeof e === 'object' &&
    e !== null &&
    typeof (e as { code?: unknown }).code === 'string' &&
    /^[0-9A-Z]{5}$/.test((e as { code: string }).code)
  );
}
