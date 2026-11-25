import { Module } from '@nestjs/common';
import { EtsyController } from './etsy.controller.js';
import { EtsyConnectionService } from './etsy-connection.service.js';

@Module({ controllers: [EtsyController], providers: [EtsyConnectionService] })
export class EtsyModule {}
