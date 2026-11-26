import { Module } from '@nestjs/common';
import { PrintifyController } from './printify.controller.js';
import { PrintifyService } from './printify.service.js';

@Module({
  controllers: [PrintifyController],
  providers: [PrintifyService],
  exports: [PrintifyService],
})
export class PrintifyModule {}
