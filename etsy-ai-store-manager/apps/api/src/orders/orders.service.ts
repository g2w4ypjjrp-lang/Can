import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
} from '@nestjs/common';
import { Decimal } from 'decimal.js';
import { calculateContribution, loadProfitContext, type ProfitInput } from '@esm/profit-engine';
import { JOBS, QUEUES } from '@esm/shared';
import { ENV, type Env } from '../config/env.js';
import { DatabaseService, type AuthContext, type Queryable } from '../database/database.service.js';
import { AuditService } from '../audit/audit.service.js';
import { QueueService } from '../queue/queue.service.js';
import { assertStoreRole } from '../common/store-access.js';
import type { RequestMeta } from '../common/request-meta.decorator.js';
import { toApprovalDto } from '../approvals/approvals.service.js';

const DELAY_SQL = `(o.status in ('open','paid','in_production') and o.shipped_at is null
   and coalesce(o.paid_at, o.placed_at) < now() - make_interval(days => ss.processing_days_max))`;

@Injectable()
export class OrdersService {
  constructor(
    @Inject(ENV) private readonly env: Env,
    private readonly db: DatabaseService,
    private readonly audit: AuditService,
    private readonly queue: QueueService,
  ) {}

  list(
    ctx: AuthContext,
    storeId: string,
    q: {
      status?: string;
      filter?: 'delayed' | 'unshipped' | 'issues';
      search?: string;
      limit: number;
      offset: number;
    },
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const params: unknown[] = [storeId];
      let where = 'o.store_id = $1';
      if (q.status) {
        params.push(q.status);
        where += ` and o.status = $${params.length}`;
      }
      if (q.filter === 'delayed')
        where += ` and (${DELAY_SQL} or exists (select 1 from public.shipments s where s.order_id = o.id and s.status in ('delayed','exception')))`;
      if (q.filter === 'unshipped')
        where += ` and o.shipped_at is null and o.status in ('open','paid','in_production')`;
      if (q.filter === 'issues')
        where += ` and exists (select 1 from public.customer_messages m where m.order_id = o.id and m.category in ('complaint','return','shipping') and m.status <> 'closed')`;
      if (q.search && /^\d+$/.test(q.search)) {
        params.push(q.search);
        where += ` and o.etsy_receipt_id::text = $${params.length}`;
      }
      const total = await db.query(
        `select count(*)::int n from public.orders o join public.store_settings ss on ss.store_id = o.store_id where ${where}`,
        params,
      );
      params.push(q.limit, q.offset);
      const r = await db.query(
        `select o.id, o.etsy_receipt_id, o.printify_order_id, o.status, o.printify_status, o.currency, o.grand_total::text,
                o.buyer_country, o.placed_at, o.paid_at, o.shipped_at, ${DELAY_SQL} as late,
                (select json_agg(json_build_object('carrier', s.carrier, 'tracking', s.tracking_number, 'status', s.status, 'source', s.source)
                          order by s.created_at) from public.shipments s where s.order_id = o.id) as shipments,
                (select string_agg(i.title || ' ×' || i.quantity, ', ') from public.order_items i where i.order_id = o.id) as items,
                (select ps.contribution::text from public.profit_snapshots ps where ps.order_id = o.id and ps.scenario = 'order_actual'
                  order by ps.calculated_at desc limit 1) as contribution,
                (select ps.decision from public.profit_snapshots ps where ps.order_id = o.id and ps.scenario = 'order_actual'
                  order by ps.calculated_at desc limit 1) as decision
           from public.orders o join public.store_settings ss on ss.store_id = o.store_id
          where ${where} order by o.placed_at desc limit $${params.length - 1} offset $${params.length}`,
        params,
      );
      const sla = (
        await db.query(
          `select processing_days_max, transit_days_max from public.store_settings where store_id = $1`,
          [storeId],
        )
      ).rows[0];
      return {
        total: total.rows[0].n,
        items: r.rows.map(toOrderRow),
        sla: {
          processingDaysMax: sla?.processing_days_max ?? 7,
          transitDaysMax: sla?.transit_days_max ?? 21,
        },
      };
    });
  }

  get(ctx: AuthContext, storeId: string, orderId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const o = (
        await db.query(
          `select o.*, ${DELAY_SQL} as late from public.orders o join public.store_settings ss on ss.store_id = o.store_id
            where o.id = $1 and o.store_id = $2`,
          [orderId, storeId],
        )
      ).rows[0];
      if (!o) throw new NotFoundException('Sipariş bulunamadı');
      const [items, shipments, refunds, snap] = await Promise.all([
        db.query(
          `select title, quantity, unit_price::text, currency, production_cost::text from public.order_items where order_id = $1`,
          [orderId],
        ),
        db.query(
          `select carrier, tracking_number, tracking_url, status, source, shipped_at, delivered_at, etsy_submitted_at
             from public.shipments where order_id = $1 order by created_at`,
          [orderId],
        ),
        db.query(
          `select id, amount::text, currency, reason, status, contribution_before::text, contribution_after::text, created_at, processed_at
             from public.refunds where order_id = $1 order by created_at`,
          [orderId],
        ),
        db.query(
          `select contribution::text, contribution_before_ads::text, decision, breakdown, warnings, complete
             from public.profit_snapshots where order_id = $1 and scenario = 'order_actual' order by calculated_at desc limit 1`,
          [orderId],
        ),
      ]);
      const isAdmin =
        (await db.query(`select private.has_store_role($1, 'admin') as ok`, [storeId])).rows[0]
          .ok === true;
      const messages = isAdmin
        ? (
            await db.query(
              `select id, direction, body, category, urgency, status, created_at from public.customer_messages
                where order_id = $1 order by created_at desc`,
              [orderId],
            )
          ).rows
        : [];
      return {
        ...toOrderRow({
          ...o,
          grand_total: o.grand_total,
          contribution: snap.rows[0]?.contribution ?? null,
          decision: snap.rows[0]?.decision ?? null,
        }),
        subtotal: o.subtotal,
        shippingTotal: o.shipping_total,
        taxTotal: o.tax_total,
        discountTotal: o.discount_total,
        printifyCostTotal: o.printify_cost_total,
        items: items.rows,
        shipmentsDetail: shipments.rows,
        refunds: refunds.rows,
        profit: snap.rows[0] ?? null,
        messages,
        fulfilledByPrintify: Boolean(o.printify_order_id),
      };
    });
  }

  /** Tracking upload (createReceiptShipment) — only for orders NOT fulfilled by Printify. */
  async requestTracking(
    ctx: AuthContext,
    storeId: string,
    orderId: string,
    b: { trackingCode: string; carrierName: string; noteToBuyer?: string; reason: string },
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const o = await lockOrder(db, storeId, orderId);
      if (!o.etsy_receipt_id) throw new ConflictException('Sipariş Etsy ile eşleşmemiş');
      if (o.printify_order_id)
        throw new ConflictException(
          'Bu sipariş Printify ile üretiliyor; Printify takip numarasını Etsy’ye kendisi iletir (çift bildirim önlenir).',
        );
      if (['cancelled', 'refunded'].includes(o.status))
        throw new ConflictException(`Sipariş "${o.status}" durumunda`);
      const dup = await db.query(
        `select 1 from public.shipments where order_id = $1 and tracking_number = $2`,
        [orderId, b.trackingCode],
      );
      if (dup.rowCount) throw new ConflictException('Bu takip numarası zaten kayıtlı');
      await assertNoPending(
        db,
        storeId,
        `action_type = 'add_tracking' and payload->>'orderId' = $2`,
        [orderId],
      );
      return insertApproval(db, {
        storeId,
        userId: ctx.userId,
        actionType: 'add_tracking',
        title: `Kargo takip no gönder: sipariş #${o.etsy_receipt_id}`,
        what: `Etsy siparişine ${b.carrierName} ${b.trackingCode} takip numarası eklenecek; Etsy alıcıya kargo bildirimi gönderir.`,
        why: b.reason,
        benefit: 'Alıcı kargoyu takip eder; sipariş Etsy’de gönderildi olarak işaretlenir.',
        currency: o.currency,
        profit: 'Doğrudan maliyet yok.',
        api: 'POST /v3/application/shops/{shop_id}/receipts/{receipt_id}/tracking (createReceiptShipment, transactions_w)',
        payload: {
          orderId,
          etsyReceiptId: String(o.etsy_receipt_id),
          trackingCode: b.trackingCode,
          carrierName: b.carrierName,
          noteToBuyer: b.noteToBuyer,
        },
        risk: 'medium',
        reauth: await needsReauth(db, ctx.userId),
        expiresDays: 3,
      });
    });
    await this.recordApproval(ctx, storeId, approval, meta);
    return toApprovalDto(approval);
  }

  /** Refund request with the exact Profit Engine impact (manual on Etsy, no API). */
  async requestRefund(
    ctx: AuthContext,
    storeId: string,
    orderId: string,
    b: { amount: string; reason: string },
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const o = await lockOrder(db, storeId, orderId);
      if (['cancelled', 'refunded'].includes(o.status))
        throw new ConflictException(`Sipariş "${o.status}" durumunda`);
      const refunded = new Decimal(
        (
          await db.query(
            `select coalesce(sum(amount),0)::text s from public.refunds where order_id = $1 and status in ('processed','approved','requested')`,
            [orderId],
          )
        ).rows[0].s,
      );
      const amount = new Decimal(b.amount);
      if (amount.plus(refunded).gt(o.grand_total))
        throw new BadRequestException(
          `İade toplamı sipariş tutarını aşamaz (kalan ${new Decimal(o.grand_total).minus(refunded).toFixed(2)} ${o.currency})`,
        );
      const impact = await refundImpact(db, storeId, orderId, amount);
      const ref = await db.query(
        `insert into public.refunds (order_id, store_id, amount, currency, reason, status, contribution_before, contribution_after, requested_by)
         values ($1,$2,$3,$4,$5,'requested',$6,$7,$8) returning id`,
        [
          orderId,
          storeId,
          amount.toFixed(2),
          o.currency,
          b.reason,
          impact?.before ?? null,
          impact?.after ?? null,
          ctx.userId,
        ],
      );
      const a = await insertApproval(db, {
        storeId,
        userId: ctx.userId,
        actionType: 'refund',
        title: `İade: sipariş #${o.etsy_receipt_id ?? orderId.slice(0, 8)} — ${amount.toFixed(2)} ${o.currency}`,
        what: `Alıcıya ${amount.toFixed(2)} ${o.currency} iade yapılacak (Etsy Satıcı Paneli → Siparişler → İade). Etsy API iade desteklemediği için siz uygulayacaksınız.`,
        why: b.reason,
        benefit: 'Müşteri memnuniyeti / anlaşmazlık ve olumsuz yorum riskinin azalması.',
        currency: o.currency,
        estimatedCost: amount.toFixed(2),
        profit: impact
          ? `Sipariş katkısı ${impact.before} → ${impact.after} ${impact.currency} (işlem ücreti orantılı iade edilir, diğer Etsy ücretleri ve üretim maliyeti geri gelmez).`
          : 'Bu sipariş için kâr hesabı yok; etki hesaplanamadı.',
        api: 'MANUEL: Etsy Satıcı Paneli (Etsy Open API v3’te iade uç noktası yok); uygulandıktan sonra burada onaylanır.',
        payload: {
          kind: 'refund',
          refundId: ref.rows[0].id,
          orderId,
          amount: amount.toFixed(2),
          manual: true,
        },
        risk: 'high',
        reauth: true,
        expiresDays: 7,
      });
      await db.query(`update public.refunds set approval_request_id = $2 where id = $1`, [
        ref.rows[0].id,
        a.id,
      ]);
      return a;
    });
    await this.recordApproval(ctx, storeId, approval, meta);
    return toApprovalDto(approval);
  }

  async requestCancel(
    ctx: AuthContext,
    storeId: string,
    orderId: string,
    reason: string,
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const o = await lockOrder(db, storeId, orderId);
      if (o.shipped_at || ['shipped', 'delivered', 'cancelled', 'refunded'].includes(o.status))
        throw new ConflictException(
          'Gönderilmiş veya kapanmış sipariş iptal edilemez; iade akışını kullanın',
        );
      await assertNoPending(
        db,
        storeId,
        `action_type = 'cancel_order' and payload->>'orderId' = $2`,
        [orderId],
      );
      return insertApproval(db, {
        storeId,
        userId: ctx.userId,
        actionType: 'cancel_order',
        title: `Sipariş iptali: #${o.etsy_receipt_id ?? orderId.slice(0, 8)}`,
        what: `Sipariş Etsy’de iptal edilecek${o.printify_order_id ? ' ve Printify’daki üretim siparişi iptal edilmeli (üretime girdiyse iptal edilemeyebilir)' : ''}.`,
        why: reason,
        benefit: 'Gönderilemeyecek bir siparişin kapatılması.',
        currency: o.currency,
        estimatedCost: o.grand_total,
        profit: `Sipariş geliri (${o.grand_total} ${o.currency}) iade edilir; üretime girmişse üretim maliyeti kayıp olur.`,
        api: 'MANUEL: Etsy Satıcı Paneli (+ Printify paneli). Etsy Open API v3’te iptal uç noktası yok.',
        payload: { kind: 'cancel_order', orderId, manual: true },
        risk: 'high',
        reauth: true,
        expiresDays: 3,
      });
    });
    await this.recordApproval(ctx, storeId, approval, meta);
    return toApprovalDto(approval);
  }

  // ---------------------------------------------------------------- customers & messages

  customers(ctx: AuthContext, storeId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select c.id, c.name, c.country, c.total_orders, c.first_order_at, c.last_order_at,
                (select coalesce(sum(o.grand_total),0)::text from public.orders o where o.customer_id = c.id and o.status <> 'cancelled') as revenue,
                (select count(*)::int from public.customer_messages m where m.customer_id = c.id and m.status not in ('sent','closed')) as open_messages
           from public.customers c where c.store_id = $1 order by c.last_order_at desc nulls last limit 200`,
        [storeId],
      );
      return r.rows.map((c) => ({
        id: c.id,
        name: c.name,
        country: c.country,
        totalOrders: c.total_orders,
        revenue: c.revenue,
        repeat: c.total_orders > 1,
        firstOrderAt: c.first_order_at,
        lastOrderAt: c.last_order_at,
        openMessages: c.open_messages,
      }));
    });
  }

  messages(ctx: AuthContext, storeId: string, status?: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `select m.*, o.etsy_receipt_id, rv.rating, t.cost_usd
           from public.customer_messages m
           left join public.orders o on o.id = m.order_id
           left join public.shop_reviews rv on rv.id = m.review_id
           left join public.ai_tasks t on t.id = m.ai_task_id
          where m.store_id = $1 and ($2::text is null or m.status = $2)
          order by case m.urgency when 'critical' then 0 when 'high' then 1 else 2 end, m.created_at desc limit 100`,
        [storeId, status ?? null],
      );
      return r.rows.map(toMessage);
    });
  }

  /** Records a message the owner pasted from Etsy Messages (no Etsy messaging API) and triages it. */
  async addMessage(
    ctx: AuthContext,
    storeId: string,
    b: { body: string; orderId?: string; receiptId?: string },
    meta: RequestMeta,
  ) {
    const id = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      let orderId = b.orderId ?? null;
      if (!orderId && b.receiptId) {
        orderId =
          (
            await db.query(
              `select id from public.orders where store_id = $1 and etsy_receipt_id = $2`,
              [storeId, b.receiptId],
            )
          ).rows[0]?.id ?? null;
        if (!orderId) throw new NotFoundException(`#${b.receiptId} numaralı sipariş bulunamadı`);
      }
      const customer = orderId
        ? (
            await db.query(
              `select customer_id from public.orders where id = $1 and store_id = $2`,
              [orderId, storeId],
            )
          ).rows[0]
        : null;
      if (orderId && !customer) throw new NotFoundException('Sipariş bulunamadı');
      const r = await db.query(
        `insert into public.customer_messages (store_id, customer_id, order_id, direction, channel, body, status, source, received_at, created_by)
         values ($1,$2,$3,'inbound','etsy',$4,'new','manual',now(),$5) returning id`,
        [storeId, customer?.customer_id ?? null, orderId, b.body, ctx.userId],
      );
      return r.rows[0].id as string;
    });
    await this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'support.message.add',
      entityType: 'customer_message',
      entityId: id,
      meta,
    });
    if (this.env.ANTHROPIC_API_KEY) await this.enqueueTriage(storeId, id, ctx.userId);
    return { id, triage: Boolean(this.env.ANTHROPIC_API_KEY) };
  }

  async retriage(ctx: AuthContext, storeId: string, messageId: string) {
    if (!this.env.ANTHROPIC_API_KEY)
      throw new ServiceUnavailableException('ANTHROPIC_API_KEY tanımlı değil');
    await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `update public.customer_messages set status = 'new' where id = $1 and store_id = $2 and status in ('new','draft_ready','failed') returning id`,
        [messageId, storeId],
      );
      if (!r.rowCount) throw new ConflictException('Bu mesaj yeniden sınıflandırılamaz');
    });
    await this.enqueueTriage(storeId, messageId, ctx.userId);
    return { queued: true };
  }

  private enqueueTriage(storeId: string, messageId: string, userId: string) {
    return this.queue.enqueue(QUEUES.sync, JOBS.supportTriage, {
      idempotencyKey: `support-triage:${messageId}:${Date.now()}`,
      storeId,
      payload: { messageId, userId },
    });
  }

  /** The reply is sent by the owner on Etsy; this records the approval of the exact text. */
  async requestSend(
    ctx: AuthContext,
    storeId: string,
    messageId: string,
    b: { text: string; reason: string },
    meta: RequestMeta,
  ) {
    const approval = await this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const m = (
        await db.query(
          `select * from public.customer_messages where id = $1 and store_id = $2 for update`,
          [messageId, storeId],
        )
      ).rows[0];
      if (!m) throw new NotFoundException('Mesaj bulunamadı');
      if (!['draft_ready', 'new', 'failed'].includes(m.status))
        throw new ConflictException(`Mesaj "${m.status}" durumunda`);
      const a = await insertApproval(db, {
        storeId,
        userId: ctx.userId,
        actionType: 'send_customer_message',
        title: m.source === 'etsy_review' ? 'Yorum yanıtı (herkese açık)' : 'Müşteri mesajı yanıtı',
        what: `Şu metin ${m.source === 'etsy_review' ? 'Etsy yorumuna herkese açık yanıt olarak' : 'Etsy Mesajlar’da alıcıya'} gönderilecek:\n\n${b.text}`,
        why: b.reason,
        benefit: 'Hızlı ve tutarlı müşteri iletişimi.',
        currency: 'USD',
        profit:
          'Doğrudan maliyet yok. Yanıt iade/indirim vaadi içermemeli; bu tür adımlar ayrı onay gerektirir.',
        api: 'MANUEL: Etsy Mesajlar / yorum yanıtı (Etsy Open API v3’te mesajlaşma uç noktası yok); gönderildikten sonra burada onaylanır.',
        payload: { kind: 'customer_message', messageId, text: b.text, manual: true },
        risk: m.source === 'etsy_review' ? 'medium' : 'low',
        reauth: false,
        expiresDays: 3,
      });
      await db.query(
        `update public.customer_messages set status = 'awaiting_approval', approval_request_id = $2, ai_draft = $3 where id = $1`,
        [messageId, a.id, b.text],
      );
      return a;
    });
    await this.recordApproval(ctx, storeId, approval, meta);
    return toApprovalDto(approval);
  }

  async closeMessage(ctx: AuthContext, storeId: string, messageId: string) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      const r = await db.query(
        `update public.customer_messages set status = 'closed' where id = $1 and store_id = $2 and status <> 'awaiting_approval' returning id`,
        [messageId, storeId],
      );
      if (!r.rowCount) throw new ConflictException('Mesaj kapatılamadı');
      return { closed: true };
    });
  }

  reviews(ctx: AuthContext, storeId: string, maxRating?: number) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'viewer');
      const r = await db.query(
        `select rv.id, rv.rating, rv.review, rv.language, rv.etsy_created_at, l.title as listing_title, rv.etsy_listing_id
           from public.shop_reviews rv left join public.listings l on l.id = rv.listing_id
          where rv.store_id = $1 and ($2::int is null or rv.rating <= $2) order by rv.etsy_created_at desc limit 100`,
        [storeId, maxRating ?? null],
      );
      const stats = await db.query(
        `select count(*)::int n, round(avg(rating)::numeric, 2)::text avg,
                count(*) filter (where rating <= 3)::int low from public.shop_reviews where store_id = $1`,
        [storeId],
      );
      return { stats: stats.rows[0], items: r.rows };
    });
  }

  async setSla(
    ctx: AuthContext,
    storeId: string,
    b: { processingDaysMax: number; transitDaysMax: number },
  ) {
    return this.db.asUser(ctx, async (db) => {
      await assertStoreRole(db, storeId, 'admin');
      await db.query(
        `update public.store_settings set processing_days_max = $2, transit_days_max = $3 where store_id = $1`,
        [storeId, b.processingDaysMax, b.transitDaysMax],
      );
      return b;
    });
  }

  private recordApproval(
    ctx: AuthContext,
    storeId: string,
    a: { id: string; action_type: string; payload: unknown },
    meta: RequestMeta,
  ) {
    return this.audit.record({
      storeId,
      actorUserId: ctx.userId,
      actorType: 'user',
      action: 'approval.create',
      entityType: 'approval_request',
      entityId: a.id,
      after: { actionType: a.action_type, payload: a.payload },
      meta,
    });
  }
}

// ---------------------------------------------------------------- helpers

/** Re-runs the order's stored Profit Engine input with the extra refund. */
async function refundImpact(db: Queryable, storeId: string, orderId: string, amount: Decimal) {
  const snap = (
    await db.query(
      `select inputs, contribution::text from public.profit_snapshots where order_id = $1 and scenario = 'order_actual'
        order by calculated_at desc limit 1`,
      [orderId],
    )
  ).rows[0];
  if (!snap) return null;
  const ctx = await loadProfitContext(db, storeId);
  const input = snap.inputs as ProfitInput;
  const policy = { ...ctx.policy, returnReserveRate: '0' };
  const before = calculateContribution(input, ctx.rules, policy);
  const after = calculateContribution(
    { ...input, refundedAmount: new Decimal(input.refundedAmount ?? 0).plus(amount).toFixed(4) },
    ctx.rules,
    policy,
  );
  return { before: before.contribution, after: after.contribution, currency: after.currency };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function lockOrder(db: Queryable, storeId: string, orderId: string): Promise<any> {
  const r = await db.query(
    `select * from public.orders where id = $1 and store_id = $2 for update`,
    [orderId, storeId],
  );
  if (!r.rowCount) throw new NotFoundException('Sipariş bulunamadı');
  return r.rows[0];
}

async function needsReauth(db: Queryable, userId: string): Promise<boolean> {
  const s = await db.query(
    `select require_reauth_for_sensitive from public.user_settings where user_id = $1`,
    [userId],
  );
  return s.rows[0]?.require_reauth_for_sensitive === true;
}

async function assertNoPending(db: Queryable, storeId: string, cond: string, params: unknown[]) {
  const r = await db.query(
    `select 1 from public.approval_requests where store_id = $1 and status in ('pending','approved','executing','awaiting_manual') and ${cond}`,
    [storeId, ...params],
  );
  if (r.rowCount) throw new ConflictException('Bu sipariş için bekleyen bir onay isteği var');
}

async function insertApproval(
  db: Queryable,
  a: {
    storeId: string;
    userId: string;
    actionType: string;
    title: string;
    what: string;
    why: string;
    benefit: string;
    currency: string;
    estimatedCost?: string;
    profit: string;
    api: string;
    payload: unknown;
    risk: 'low' | 'medium' | 'high';
    reauth: boolean;
    expiresDays: number;
  },
) {
  const r = await db.query(
    `insert into public.approval_requests
       (store_id, requested_by_type, requested_by_user_id, action_type, title, what, why, expected_benefit,
        estimated_cost, cost_currency, profit_impact, api_operation, payload, risk_level, requires_reauth, expires_at)
     values ($1,'user',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14, now() + make_interval(days => $15)) returning *`,
    [
      a.storeId,
      a.userId,
      a.actionType,
      a.title,
      a.what,
      a.why,
      a.benefit,
      a.estimatedCost ?? '0',
      a.currency,
      a.profit,
      a.api,
      JSON.stringify(a.payload),
      a.risk,
      a.reauth,
      a.expiresDays,
    ],
  );
  return r.rows[0];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toOrderRow(o: any) {
  return {
    id: o.id,
    etsyReceiptId: o.etsy_receipt_id === null ? null : String(o.etsy_receipt_id),
    printifyOrderId: o.printify_order_id,
    status: o.status,
    printifyStatus: o.printify_status,
    currency: o.currency,
    grandTotal: o.grand_total,
    buyerCountry: o.buyer_country,
    placedAt: o.placed_at,
    paidAt: o.paid_at,
    shippedAt: o.shipped_at,
    late: Boolean(o.late),
    shipments: o.shipments ?? [],
    items: o.items ?? null,
    contribution: o.contribution ?? null,
    decision: o.decision ?? null,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toMessage(m: any) {
  return {
    id: m.id,
    orderId: m.order_id,
    etsyReceiptId:
      m.etsy_receipt_id === null || m.etsy_receipt_id === undefined
        ? null
        : String(m.etsy_receipt_id),
    source: m.source,
    rating: m.rating ?? null,
    body: m.body,
    status: m.status,
    category: m.category,
    sentiment: m.sentiment,
    urgency: m.urgency,
    issues: m.issues,
    suggestedAction: m.suggested_action,
    draft: m.ai_draft,
    draftLanguage: m.draft_language,
    internalNote: m.internal_note,
    aiError: m.ai_error,
    costUsd: m.cost_usd ?? null,
    receivedAt: m.received_at,
    sentAt: m.sent_at,
  };
}
