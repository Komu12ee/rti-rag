from services.postgres_db import test_database_connection


def main() -> None:
    result = test_database_connection()

    print("\n" + "=" * 65)
    print("POSTGRESQL LIVE-BACKEND CONNECTION TEST")
    print("=" * 65)
    print(f"Database:           {result['database_name']}")
    print(f"User:               {result['database_user']}")
    print(f"Active assignments: {result['active_assignments']}")
    print("=" * 65)


if __name__ == "__main__":
    main()