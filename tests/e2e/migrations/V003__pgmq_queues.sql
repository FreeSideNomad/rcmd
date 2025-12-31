-- Create PGMQ queues for E2E testing
SELECT pgmq.create('e2e__commands');
SELECT pgmq.create('e2e__replies');
