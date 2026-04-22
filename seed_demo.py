"""Run once to add demo services and working schedule."""
import asyncio
import database as db


async def main():
    await db.init_db()

    # Services
    await db.add_service("Мужская стрижка", 1500, 60)
    await db.add_service("Коррекция бороды", 700, 30)
    await db.add_service("Женская стрижка", 2500, 90)
    await db.add_service("Стрижка + борода", 2000, 90)

    # Working hours: Mon–Sat 10:00–20:00, Sun off
    for day in range(6):  # 0=Mon to 5=Sat
        await db.set_working_hours(day, "10:00", "20:00")

    # Master info
    await db.set_setting('master_name', 'Имя Мастера')
    await db.set_setting('master_bio', 'Hairstylist')
    await db.set_setting('master_location', 'Москва, ул. Примерная, д.1')

    print("✅ Demo data added!")


asyncio.run(main())
