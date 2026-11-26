import { Module } from '@nestjs/common';
import { DesignsController } from './designs.controller.js';
import { DesignsService } from './designs.service.js';
import { PrintifyModule } from '../printify/printify.module.js';

@Module({
  imports: [PrintifyModule],
  controllers: [DesignsController],
  providers: [DesignsService],
})
export class DesignsModule {}
